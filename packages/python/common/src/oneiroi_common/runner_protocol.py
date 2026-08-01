from enum import StrEnum
from typing import Any, Literal

from pydantic import Field

from oneiroi_common.compute import ContractModel, PipelineSpec

RUNNER_CONTROL_STREAM_TEMPLATE = "oneiroi:gpu:{gpu_id}:control"
SLOT_CONTROL_STREAM_TEMPLATE = "oneiroi:slot:{slot_id}:control"
SLOT_JOB_STREAM_TEMPLATE = "oneiroi:slot:{slot_id}:jobs"
JOB_EVENT_STREAM_TEMPLATE = "oneiroi:job:{job_id}:events"
COMMAND_RESULT_STREAM_TEMPLATE = "oneiroi:command:{command_id}:result"
HEARTBEAT_STREAM = "oneiroi:runner:heartbeats"


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


class RunnerCommandResult(ContractModel):
    command_id: str
    status: Literal["succeeded", "failed"]
    payload: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


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
