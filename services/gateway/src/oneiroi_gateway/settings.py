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
    nvml_inventory_enabled: bool = False
    gpu_allowlist: str = ""
    gpu_minimum_vram_mib: int = Field(default=70_000, ge=0)
    gpu_idle_vram_threshold_mib: int = Field(default=2_048, ge=0)
    runner_heartbeat_timeout_seconds: float = Field(default=30, gt=0, le=300)

    @property
    def allowed_gpu_ids(self) -> frozenset[str] | None:
        values = frozenset(item.strip() for item in self.gpu_allowlist.split(",") if item.strip())
        return values or None


@lru_cache
def get_settings() -> GatewaySettings:
    return GatewaySettings()
