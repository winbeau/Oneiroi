from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class GatewaySettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="ONEIROI_GATEWAY_",
        extra="ignore",
    )

    environment: str = "development"
    database_url: str = "postgresql+asyncpg://oneiroi:oneiroi-local@127.0.0.1:5432/oneiroi"
    redis_url: str = "redis://127.0.0.1:6379/0"
    storage_root: Path = Path(".data/storage")
    max_upload_bytes: int = Field(default=20 * 1024 * 1024, gt=0)


@lru_cache
def get_settings() -> GatewaySettings:
    return GatewaySettings()
