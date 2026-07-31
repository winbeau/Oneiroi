from fastapi import APIRouter, FastAPI

from oneiroi_bff.settings import BffSettings, get_settings
from oneiroi_common.api import ServiceHealth

__version__ = "0.1.0"


def create_app(settings: BffSettings | None = None) -> FastAPI:
    app_settings = settings or get_settings()
    app = FastAPI(
        title="Oneiroi Studio BFF",
        version=__version__,
        docs_url="/docs" if app_settings.environment == "development" else None,
        redoc_url=None,
    )

    system_router = APIRouter(tags=["system"])

    @system_router.get("/healthz", response_model=ServiceHealth)
    async def healthz() -> ServiceHealth:
        return ServiceHealth(service="bff", version=__version__)

    @system_router.get("/v1/system/health", response_model=ServiceHealth)
    async def system_health() -> ServiceHealth:
        return ServiceHealth(service="bff", version=__version__)

    app.include_router(system_router)
    return app


app = create_app()
