from fastapi import APIRouter, FastAPI

from oneiroi_common.api import ServiceHealth
from oneiroi_common.jobs import QueueTier
from oneiroi_gateway.settings import GatewaySettings, get_settings

__version__ = "0.1.0"


def create_app(settings: GatewaySettings | None = None) -> FastAPI:
    app_settings = settings or get_settings()
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
    return app


app = create_app()
