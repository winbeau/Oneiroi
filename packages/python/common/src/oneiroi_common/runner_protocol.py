from enum import StrEnum
from typing import Any

from pydantic import Field

from oneiroi_common.compute import ContractModel, PipelineSpec


class RunnerCommandType(StrEnum):
    LOAD_PROFILE = "load_profile"
    UNLOAD = "unload"
    RUN_JOB = "run_job"
    CANCEL_JOB = "cancel_job"
    HEARTBEAT = "heartbeat"


class RunnerCommand(ContractModel):
    command_id: str
    command_type: RunnerCommandType
    slot_id: str
    pipeline_spec: PipelineSpec | None = None
    job_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class RunnerHeartbeat(ContractModel):
    runner_id: str
    slot_id: str
    gpu_id: str
    physical_index: int
    state: str
    vram_used_mib: int = Field(ge=0)
    vram_total_mib: int = Field(ge=0)
    worker_pid: int | None = None
    occurred_at: str
