from fastapi import APIRouter, FastAPI

from oneiroi_common.api import ServiceHealth
from oneiroi_common.jobs import QueueTier
from oneiroi_gateway.db.session import create_engine, create_session_factory
from oneiroi_gateway.redis.control_streams import RedisDirectedStreams
from oneiroi_gateway.redis.leases import RedisLeaseStore
from oneiroi_gateway.repositories.sql_studio import SqlStudioRepository
from oneiroi_gateway.repositories.studio import InMemoryStudioRepository, StudioRepository
from oneiroi_gateway.routes.assets import create_asset_router
from oneiroi_gateway.routes.compute import create_compute_router
from oneiroi_gateway.routes.conversations import create_conversation_router
from oneiroi_gateway.routes.jobs import create_job_router
from oneiroi_gateway.routes.uploads import create_upload_router
from oneiroi_gateway.services.artifact_service import ArtifactService
from oneiroi_gateway.services.capabilities import CapabilityService
from oneiroi_gateway.services.compute_sessions import (
    ComputeSessionService,
    UnavailableComputeBackend,
)
from oneiroi_gateway.services.gpu_inventory import (
    GpuInventoryService,
    InMemoryInventoryProvider,
    NvmlInventoryProvider,
)
from oneiroi_gateway.services.job_dispatcher import (
    InMemoryJobDispatcher,
    JobDispatcher,
    RedisJobDispatcher,
)
from oneiroi_gateway.services.job_execution import JobExecutor
from oneiroi_gateway.services.job_scheduler import JobScheduler
from oneiroi_gateway.services.job_service import JobService
from oneiroi_gateway.settings import GatewaySettings, get_settings

__version__ = "0.1.0"


def create_app(
    settings: GatewaySettings | None = None,
    *,
    inventory_service: GpuInventoryService | None = None,
    compute_session_service: ComputeSessionService | None = None,
    capability_service: CapabilityService | None = None,
    repository: StudioRepository | None = None,
    job_dispatcher: JobDispatcher | None = None,
    job_executor: JobExecutor | None = None,
    job_service: JobService | None = None,
) -> FastAPI:
    app_settings = settings or get_settings()
    if inventory_service is None:
        provider = (
            NvmlInventoryProvider(
                allowlist=app_settings.allowed_gpu_ids,
                minimum_vram_mib=app_settings.gpu_minimum_vram_mib,
                idle_vram_threshold_mib=app_settings.gpu_idle_vram_threshold_mib,
            )
            if app_settings.nvml_inventory_enabled
            else InMemoryInventoryProvider()
        )
        inventory_service = GpuInventoryService(provider)
    if compute_session_service is None:
        compute_session_service = ComputeSessionService(
            inventory_service,
            UnavailableComputeBackend(),
            leases=(
                RedisLeaseStore(app_settings.redis_url)
                if app_settings.redis_leases_enabled
                else None
            ),
        )
    capability_service = capability_service or CapabilityService()
    database_engine = None
    if repository is None:
        if app_settings.persistence_enabled:
            database_engine = create_engine(app_settings.database_url)
            repository = SqlStudioRepository(create_session_factory(database_engine))
        else:
            repository = InMemoryStudioRepository()
    artifacts = ArtifactService(
        repository,
        app_settings.storage_root,
        max_upload_bytes=app_settings.max_upload_bytes,
    )
    redis_streams = None
    if job_dispatcher is None:
        if app_settings.redis_job_streams_enabled:
            redis_streams = RedisDirectedStreams(app_settings.redis_url)
            job_dispatcher = RedisJobDispatcher(redis_streams)
        else:
            job_dispatcher = InMemoryJobDispatcher()
    if job_service is None:
        job_service = JobService(
            repository,
            compute_session_service,
            capability_service,
            JobScheduler(compute_session_service),
            job_dispatcher,
            artifacts,
            job_executor,
        )
    app = FastAPI(
        title="Oneiroi Studio Gateway",
        version=__version__,
        docs_url="/docs" if app_settings.environment == "development" else None,
        redoc_url=None,
    )

    system_router = APIRouter(tags=["system"])

    @system_router.get("/healthz", response_model=ServiceHealth)
    async def healthz() -> ServiceHealth:
        return ServiceHealth(service="gateway", version=__version__)

    @system_router.get("/v1/system/queues")
    async def queue_catalog() -> dict[str, list[str]]:
        return {"queues": [tier.value for tier in QueueTier]}

    app.include_router(system_router)
    app.state.database_engine = database_engine
    app.state.redis_streams = redis_streams
    app.state.repository = repository
    app.state.job_service = job_service
    app.include_router(
        create_compute_router(inventory_service, compute_session_service, capability_service)
    )
    app.include_router(create_conversation_router(repository))
    app.include_router(create_asset_router(repository, artifacts))
    app.include_router(create_upload_router(artifacts))
    app.include_router(create_job_router(job_service))
    return app


app = create_app()
