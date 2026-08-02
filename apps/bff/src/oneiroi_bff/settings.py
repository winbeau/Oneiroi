from functools import lru_cache
from pathlib import Path

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
    max_agent_json_bytes: int = Field(default=256 * 1024, gt=0, le=1024 * 1024)
    access_issuer: str = ""
    access_audience: str = ""
    access_jwks_url: str = ""
    access_jwks_cache_seconds: float = Field(default=300, gt=0, le=86_400)
    access_clock_skew_seconds: float = Field(default=30, ge=0, le=300)
    allowed_origins: str = "https://video.icthub.top"
    require_inbound_service_auth: bool = False
    service_private_key_file: Path | None = None
    service_public_key_file: Path | None = None
    service_assertion_issuer: str = "oneiroi-pi-bff"
    service_assertion_audience: str = "oneiroi-h100-gateway"
    service_assertion_key_id: str = "oneiroi-pi-1"
    service_assertion_lifetime_seconds: int = Field(default=300, ge=30, le=600)
    service_assertion_clock_skew_seconds: float = Field(default=120, ge=0, le=300)

    @property
    def trusted_origins(self) -> frozenset[str]:
        return frozenset(
            origin.strip().rstrip("/")
            for origin in self.allowed_origins.split(",")
            if origin.strip()
        )


@lru_cache
def get_settings() -> BffSettings:
    return BffSettings()
