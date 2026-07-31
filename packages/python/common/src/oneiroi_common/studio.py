from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field

from oneiroi_common.compute import ContractModel, ProfileTier
from oneiroi_common.jobs import JobStatus, QueueTier


class ConversationCreate(ContractModel):
    title: Annotated[str, Field(default="未命名创作", min_length=1, max_length=100)]


class ConversationPut(ContractModel):
    title: Annotated[str, Field(min_length=1, max_length=100)]


class ConversationResponse(ContractModel):
    id: str
    title: str
    created_at: datetime
    updated_at: datetime


class AssetResponse(ContractModel):
    id: str
    type: Literal["image", "video", "template"]
    title: str
    created_at: datetime
    media_type: str
    size_bytes: int = Field(ge=0)
    width: int | None = Field(default=None, ge=1)
    height: int | None = Field(default=None, ge=1)
    source_job_id: str | None = None
    preview_url: str | None = None


class GenerationDraft(ContractModel):
    mode: Literal["I2V"] = "I2V"
    prompt: Annotated[str, Field(min_length=1, max_length=4_000)]
    negative_prompt: str = ""
    queue: QueueTier = QueueTier.FAST
    profile: ProfileTier = ProfileTier.FAST
    ratio: Literal["16:9", "9:16", "1:1"] = "16:9"
    resolution: Literal["720p", "1080p"] = "720p"
    duration: Literal[5, 8, 10] = 5
    seed: int = 42
    first_strength: float = Field(default=1, ge=0, le=1)
    last_strength: float = Field(default=1, ge=0, le=1)
    enhance_prompt: bool = False
    quantization: Literal["fp8-cast", "none"] = "fp8-cast"
    offload: Literal["none", "cpu"] = "none"
    first_frame_asset_id: str | None = None
    last_frame_asset_id: str | None = None


class JobCreate(ContractModel):
    conversation_id: str
    compute_session_id: str
    draft: GenerationDraft


class GpuAssignment(ContractModel):
    id: str
    physical_index: int


class JobOutput(ContractModel):
    asset_id: str
    file_url: str
    manifest_url: str
    media_type: str = "video/mp4"
    size_bytes: int = Field(ge=0)


class JobError(ContractModel):
    code: str
    message: str
    retryable: bool = False


class JobResponse(ContractModel):
    id: str
    conversation_id: str
    compute_session_id: str
    created_at: datetime
    updated_at: datetime
    stage: JobStatus
    progress: int = Field(ge=0, le=100)
    draft: GenerationDraft
    queue_position: int | None = Field(default=None, ge=1)
    profile_id: str | None = None
    gpu: GpuAssignment | None = None
    attempt: int = Field(default=1, ge=1)
    warm_start: bool | None = None
    phase: str | None = None
    current_step: int | None = Field(default=None, ge=0)
    total_steps: int | None = Field(default=None, ge=0)
    output: JobOutput | None = None
    error: JobError | None = None


class JobEventResponse(ContractModel):
    id: int
    job_id: str
    event_type: str
    payload: dict[str, object]
    created_at: datetime


class JobManifest(ContractModel):
    job_id: str
    attempt: int
    profile_id: str
    pipeline_spec_hash: str | None = None
    request: dict[str, object]
    metrics: dict[str, object]
    output: dict[str, object]
