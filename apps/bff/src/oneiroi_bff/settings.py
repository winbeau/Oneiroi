from functools import lru_cache

from pydantic import Field, HttpUrl
from pydantic_settings import BaseSettings, SettingsConfigDict


class BffSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="ONEIROI_BFF_",
        extra="ignore",
    )

    environment: str = "development"
    gateway_base_url: HttpUrl = HttpUrl("http://127.0.0.1:8010")
    request_timeout_seconds: float = Field(default=300, gt=0, le=7_200)
    max_upload_bytes: int = Field(default=20 * 1024 * 1024, gt=0)


@lru_cache
def get_settings() -> BffSettings:
    return BffSettings()
