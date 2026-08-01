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
    persistence_enabled: bool = False
    redis_url: str = "redis://127.0.0.1:6379/0"
    redis_leases_enabled: bool = False
    redis_job_streams_enabled: bool = False
    redis_runner_backend_enabled: bool = False
    redis_lease_ttl_seconds: float = Field(default=300, gt=10, le=86_400)
    compute_idle_ttl_seconds: float = Field(default=86_400, gt=0, le=604_800)
    runner_command_timeout_seconds: float = Field(default=900, gt=0, le=3_600)
    runner_job_timeout_seconds: float = Field(default=7_200, gt=0, le=86_400)
    storage_root: Path = Path(".data/storage")
    max_upload_bytes: int = Field(default=20 * 1024 * 1024, gt=0)
    nvml_inventory_enabled: bool = False
    gpu_allowlist: str = ""
    gpu_minimum_vram_mib: int = Field(default=70_000, ge=0)
    gpu_idle_vram_threshold_mib: int = Field(default=2_048, ge=0)
    runner_heartbeat_timeout_seconds: float = Field(default=30, gt=0, le=300)
    service_public_key_file: Path | None = None
    service_assertion_issuer: str = "oneiroi-pi-bff"
    service_assertion_audience: str = "oneiroi-h100-gateway"
    service_assertion_clock_skew_seconds: float = Field(default=120, ge=0, le=300)
    ltx_git_commit: str = ""
    ltx_distilled_checkpoint_path: str = ""
    ltx_distilled_checkpoint_sha256: str = ""
    ltx_dev_checkpoint_path: str = ""
    ltx_dev_checkpoint_sha256: str = ""
    ltx_distilled_lora_path: str = ""
    ltx_distilled_lora_sha256: str = ""
    ltx_upsampler_path: str = ""
    ltx_upsampler_sha256: str = ""
    ltx_gemma_root: str = ""
    ltx_gemma_revision: str = ""

    @property
    def allowed_gpu_ids(self) -> frozenset[str] | None:
        values = frozenset(item.strip() for item in self.gpu_allowlist.split(",") if item.strip())
        return values or None


@lru_cache
def get_settings() -> GatewaySettings:
    return GatewaySettings()
