from enum import StrEnum
from typing import Any

from pydantic import Field

from oneiroi_common.compute import ContractModel


class RunnerEventType(StrEnum):
    HEARTBEAT = "runner.heartbeat"
    SLOT_UPDATED = "compute.slot.updated"
    SESSION_UPDATED = "compute.session.updated"
    SESSION_READY = "compute.session.ready"
    SESSION_DEGRADED = "compute.session.degraded"
    SESSION_RELEASED = "compute.session.released"
    JOB_UPDATED = "job.updated"


class RunnerEvent(ContractModel):
    id: int | None = None
    event_type: RunnerEventType
    subject_id: str
    payload: dict[str, Any] = Field(default_factory=dict)
    occurred_at: str
