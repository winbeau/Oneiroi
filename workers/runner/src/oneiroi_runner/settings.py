from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from oneiroi_common.jobs import QueueTier


class RunnerSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="ONEIROI_RUNNER_",
        extra="ignore",
    )

    environment: str = "development"
    redis_url: str = "redis://127.0.0.1:6379/0"
    queue: QueueTier = QueueTier.FAST
    name: str = "runner-unconfigured"
    gpu_id: str = "GPU-unconfigured"
    physical_index: int = Field(default=0, ge=0)
    heartbeat_seconds: float = Field(default=10, gt=0, le=60)
    storage_root: Path = Path(".data/storage/jobs")
    adapter_name: str = "auto"
    load_timeout_seconds: float = Field(default=900, gt=0, le=3_600)
    job_timeout_seconds: float = Field(default=7_200, gt=0, le=86_400)
    unload_timeout_seconds: float = Field(default=30, gt=0, le=300)
    baseline_vram_mib: int = Field(default=0, ge=0)
    release_tolerance_mib: int = Field(default=512, ge=0)


@lru_cache
def get_settings() -> RunnerSettings:
    return RunnerSettings()
