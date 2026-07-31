from enum import StrEnum


class QueueTier(StrEnum):
    FAST = "fast"
    HQ = "hq"


class JobStatus(StrEnum):
    DRAFT = "draft"
    UPLOADED = "uploaded"
    QUEUED = "queued"
    ASSIGNED = "assigned"
    PREPARING = "preparing"
    GENERATING = "generating"
    ENCODING = "encoding"
    SUCCEEDED = "succeeded"
    CANCELLED = "cancelled"
    FAILED = "failed"

    @property
    def is_terminal(self) -> bool:
        return self in {self.SUCCEEDED, self.CANCELLED, self.FAILED}
