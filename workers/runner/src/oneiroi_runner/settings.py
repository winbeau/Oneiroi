from functools import lru_cache

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
    name: str = "fast-0"
    gpu_device: int = Field(default=0, ge=0)
    heartbeat_seconds: float = Field(default=10, gt=0, le=60)


@lru_cache
def get_settings() -> RunnerSettings:
    return RunnerSettings()
