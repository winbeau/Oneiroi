from fastapi import APIRouter, FastAPI

from oneiroi_common.api import ServiceHealth
from oneiroi_common.jobs import QueueTier
from oneiroi_gateway.redis.leases import RedisLeaseStore
from oneiroi_gateway.routes.compute import create_compute_router
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
from oneiroi_gateway.settings import GatewaySettings, get_settings

__version__ = "0.1.0"


def create_app(
    settings: GatewaySettings | None = None,
    *,
    inventory_service: GpuInventoryService | None = None,
    compute_session_service: ComputeSessionService | None = None,
    capability_service: CapabilityService | None = None,
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
    app.include_router(
        create_compute_router(inventory_service, compute_session_service, capability_service)
    )
    return app


app = create_app()
