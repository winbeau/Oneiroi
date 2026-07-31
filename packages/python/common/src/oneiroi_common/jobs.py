from enum import StrEnum


class QueueTier(StrEnum):
    FAST = "fast"
    HQ = "hq"


class JobStatus(StrEnum):
    DRAFT = "draft"
    UPLOADED = "uploaded"
    QUEUED = "queued"
    ASSIGNED = "assigned"
    LOADING_MODEL = "loading_model"
    PREPARING = "preparing"
    GENERATING = "generating"
    ENCODING = "encoding"
    CANCEL_REQUESTED = "cancel_requested"
    SUCCEEDED = "succeeded"
    CANCELLED = "cancelled"
    FAILED = "failed"

    @property
    def is_terminal(self) -> bool:
        return self in {self.SUCCEEDED, self.CANCELLED, self.FAILED}
