import asyncio
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI, Request, status
from fastapi.responses import JSONResponse

from oneiroi_common.api import ServiceHealth
from oneiroi_common.identity import SERVICE_ASSERTION_HEADER
from oneiroi_common.jobs import QueueTier
from oneiroi_gateway.db.session import create_engine, create_session_factory
from oneiroi_gateway.redis.control_streams import RedisDirectedStreams
from oneiroi_gateway.redis.leases import RedisLeaseStore
from oneiroi_gateway.repositories.compute import SqlComputeStateRepository
from oneiroi_gateway.repositories.sql_studio import SqlStudioRepository
from oneiroi_gateway.repositories.studio import InMemoryStudioRepository, StudioRepository
from oneiroi_gateway.routes.assets import create_asset_router
from oneiroi_gateway.routes.compute import create_compute_router
from oneiroi_gateway.routes.conversations import create_conversation_router
from oneiroi_gateway.routes.jobs import create_job_router
from oneiroi_gateway.routes.uploads import create_upload_router
from oneiroi_gateway.service_auth import (
    ServiceAssertionValidator,
    ServiceAuthConfigurationError,
    ServiceAuthenticationError,
)
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
from oneiroi_gateway.services.job_execution import JobExecutor, RedisJobExecutor
from oneiroi_gateway.services.job_scheduler import JobScheduler
from oneiroi_gateway.services.job_service import JobService
from oneiroi_gateway.services.pipeline_profiles import PipelineProfileCatalog
from oneiroi_gateway.services.runner_backend import RedisComputeBackend
from oneiroi_gateway.services.runner_heartbeats import RunnerHeartbeatMonitor
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
    service_validator = ServiceAssertionValidator(
        app_settings.service_public_key_file,
        issuer=app_settings.service_assertion_issuer,
        audience=app_settings.service_assertion_audience,
        clock_skew_seconds=app_settings.service_assertion_clock_skew_seconds,
    )
    managed_compute_service = compute_session_service is None
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
    if app_settings.redis_runner_backend_enabled and not app_settings.redis_leases_enabled:
        raise RuntimeError("Redis Runner backend requires Redis GPU leases")
    redis_streams = (
        RedisDirectedStreams(app_settings.redis_url)
        if app_settings.redis_runner_backend_enabled
        or app_settings.redis_job_streams_enabled
        else None
    )
    if compute_session_service is None:
        compute_backend = (
            RedisComputeBackend(
                redis_streams,
                PipelineProfileCatalog.from_settings(app_settings),
                command_timeout_seconds=app_settings.runner_command_timeout_seconds,
            )
            if app_settings.redis_runner_backend_enabled and redis_streams is not None
            else UnavailableComputeBackend()
        )
        compute_session_service = ComputeSessionService(
            inventory_service,
            compute_backend,
            leases=(
                RedisLeaseStore(app_settings.redis_url)
                if app_settings.redis_leases_enabled
                else None
            ),
            lease_ttl_seconds=app_settings.redis_lease_ttl_seconds,
            idle_ttl_seconds=app_settings.compute_idle_ttl_seconds,
        )
    capability_service = capability_service or CapabilityService()
    database_engine = None
    database_sessions = None
    if repository is None:
        if app_settings.persistence_enabled:
            database_engine = create_engine(app_settings.database_url)
            database_sessions = create_session_factory(database_engine)
            repository = SqlStudioRepository(database_sessions)
        else:
            repository = InMemoryStudioRepository()
    if managed_compute_service and database_sessions is not None:
        compute_session_service.state_repository = SqlComputeStateRepository(database_sessions)
    artifacts = ArtifactService(
        repository,
        app_settings.storage_root,
        max_upload_bytes=app_settings.max_upload_bytes,
    )
    if job_dispatcher is None:
        if redis_streams is not None and (
            app_settings.redis_job_streams_enabled
            or app_settings.redis_runner_backend_enabled
        ):
            job_dispatcher = RedisJobDispatcher(redis_streams)
        else:
            job_dispatcher = InMemoryJobDispatcher()
    if job_executor is None and app_settings.redis_runner_backend_enabled:
        assert redis_streams is not None
        job_executor = RedisJobExecutor(
            redis_streams,
            timeout_seconds=app_settings.runner_job_timeout_seconds,
        )
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
    heartbeat_monitor = (
        RunnerHeartbeatMonitor(
            app_settings.redis_url,
            compute_session_service,
            timeout_seconds=app_settings.runner_heartbeat_timeout_seconds,
        )
        if app_settings.redis_runner_backend_enabled
        else None
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        await compute_session_service.restore()
        await job_service.restore_inflight()
        heartbeat_stop = asyncio.Event()
        heartbeat_task = (
            asyncio.create_task(
                heartbeat_monitor.run(heartbeat_stop),
                name="runner-heartbeat-monitor",
            )
            if heartbeat_monitor is not None
            else None
        )
        try:
            yield
        finally:
            if heartbeat_task is not None and heartbeat_monitor is not None:
                await heartbeat_monitor.stop(heartbeat_task, heartbeat_stop)
            await job_service.close()
            await compute_session_service.close()
            if redis_streams is not None:
                await redis_streams.close()
            if database_engine is not None:
                await database_engine.dispose()

    app = FastAPI(
        title="Oneiroi Studio Gateway",
        version=__version__,
        docs_url="/docs" if app_settings.environment == "development" else None,
        redoc_url=None,
        lifespan=lifespan,
    )

    @app.middleware("http")
    async def require_private_identity(request: Request, call_next):
        protected = request.url.path.startswith("/v1/") and not request.url.path.startswith(
            "/v1/system/"
        )
        if app_settings.environment != "development" and protected:
            user = request.headers.get("X-Oneiroi-User", "").strip()
            assertion = request.headers.get(SERVICE_ASSERTION_HEADER, "")
            try:
                asserted_owner = service_validator.validate(assertion)
            except ServiceAuthConfigurationError:
                return JSONResponse(
                    {"detail": "AUTHENTICATION_NOT_CONFIGURED"},
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                )
            except ServiceAuthenticationError:
                return JSONResponse(
                    {"detail": "AUTHENTICATION_REQUIRED"},
                    status_code=status.HTTP_401_UNAUTHORIZED,
                )
            if not user or user != asserted_owner:
                return JSONResponse(
                    {"detail": "AUTHENTICATION_REQUIRED"},
                    status_code=status.HTTP_401_UNAUTHORIZED,
                )
        return await call_next(request)

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
