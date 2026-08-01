import hashlib
import json
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

MAX_GPU_COUNT = 4
FAST_PROFILE_ID = "ltx23-distilled-fast-v1"
HQ_PROFILE_ID = "ltx23-dev-hq-v1"


def to_camel(value: str) -> str:
    head, *tail = value.split("_")
    return head + "".join(part[:1].upper() + part[1:] for part in tail)


class ContractModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
    )


class GpuState(StrEnum):
    OFFLINE = "offline"
    EMPTY = "empty"
    RESERVED = "reserved"
    LOADING = "loading"
    READY = "ready"
    BUSY = "busy"
    DRAINING = "draining"
    UNLOADING = "unloading"
    ERROR = "error"
    FOREIGN_BUSY = "foreign_busy"


class ComputeSessionState(StrEnum):
    REQUESTED = "requested"
    ALLOCATING = "allocating"
    LOADING = "loading"
    READY = "ready"
    DEGRADED = "degraded"
    FAILED = "failed"
    DRAINING = "draining"
    RELEASING = "releasing"
    RELEASED = "released"


class SelectionMode(StrEnum):
    AUTO = "auto"
    MANUAL = "manual"


class ProfilePolicy(StrEnum):
    BALANCED = "balanced"


class ProfileTier(StrEnum):
    FAST = "fast"
    HQ = "hq"


class ReleasePolicy(StrEnum):
    WHEN_IDLE = "when_idle"
    CANCEL_RUNNING = "cancel_running"


class ProfilePlan(ContractModel):
    fast: Annotated[int, Field(ge=0, le=MAX_GPU_COUNT)]
    hq: Annotated[int, Field(ge=0, le=MAX_GPU_COUNT)]

    @property
    def total(self) -> int:
        return self.fast + self.hq


class GpuInfo(ContractModel):
    id: str
    physical_index: Annotated[int, Field(ge=0)]
    name: str
    vram_total_mib: Annotated[int, Field(alias="vramTotalMiB", ge=0)]
    vram_used_mib: Annotated[int, Field(alias="vramUsedMiB", ge=0)] = 0
    utilization_percent: Annotated[float, Field(ge=0, le=100)] = 0
    temperature_celsius: Annotated[float, Field(ge=0)] = 0
    state: GpuState = GpuState.EMPTY
    eligible: bool = False
    unavailable_reason: str | None = None
    external_process_count: Annotated[int, Field(ge=0)] = 0
    last_heartbeat_at: str | None = None

    @field_validator("id")
    @classmethod
    def stable_uuid_is_required(cls, value: str) -> str:
        if not value.startswith("GPU-"):
            raise ValueError("GPU id must be a stable NVML UUID")
        return value


class GpuInventoryResponse(ContractModel):
    requested_default: int = 4
    maximum_selectable: int = MAX_GPU_COUNT
    gpus: list[GpuInfo]


class PipelineSpec(ContractModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
        frozen=True,
    )

    profile_id: str
    tier: ProfileTier
    ltx_git_commit: str
    checkpoint_path: str
    checkpoint_sha256: str
    upsampler_path: str
    upsampler_sha256: str
    gemma_root: str
    gemma_revision: str
    lora_paths_and_scales: tuple[tuple[str, float], ...] = ()
    lora_sha256s: tuple[str, ...] = ()
    quantization: Literal["fp8-cast", "none"] = "fp8-cast"
    offload: Literal["none", "cpu"] = "none"
    dtype: str = "bfloat16"
    attention_backend: str = "sdpa"
    compile_mode: str = "disabled"
    runtime_policy_version: str = "oneiroi-v1"

    @property
    def identity(self) -> str:
        payload = json.dumps(
            self.model_dump(mode="json", by_alias=True),
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode()).hexdigest()


class ComputeSlot(ContractModel):
    id: str
    gpu_id: str
    physical_index: int
    state: GpuState
    profile: ProfileTier | None = None
    load_stage: str | None = None
    load_progress: int = Field(default=0, ge=0, le=100)
    pipeline_spec_hash: str | None = None
    last_error: str | None = None


class ProfileCapability(ContractModel):
    id: str
    tier: ProfileTier
    available: bool
    resolutions: list[str] = Field(default_factory=list)
    durations: list[int] = Field(default_factory=list)
    unavailable_reason: str | None = None


class ComputeCapabilitiesResponse(ContractModel):
    requested_default: int = 4
    maximum_selectable: int = MAX_GPU_COUNT
    profiles: list[ProfileCapability]


class ComputeSessionCreate(ContractModel):
    requested_gpu_count: Annotated[int, Field(default=4, ge=1, le=MAX_GPU_COUNT)]
    selection_mode: SelectionMode = SelectionMode.AUTO
    gpu_ids: list[str] = Field(default_factory=list)
    profile_policy: ProfilePolicy = ProfilePolicy.BALANCED
    allow_partial: bool = True


class ComputeSessionRelease(ContractModel):
    policy: ReleasePolicy = ReleasePolicy.WHEN_IDLE
    confirmed: bool = False


class ComputeSessionSnapshot(ContractModel):
    id: str
    owner_id: str
    state: ComputeSessionState
    requested_gpu_count: int
    allocated_gpu_count: int
    selection_mode: SelectionMode
    profile_policy: ProfilePolicy
    allow_partial: bool
    profile_plan: ProfilePlan
    slots: list[ComputeSlot] = Field(default_factory=list)
    error_code: str | None = None
    error_message: str | None = None
    created_at: str
    ready_at: str | None = None
    released_at: str | None = None


def allocated_gpu_count(requested: int, eligible_count: int, allow_partial: bool = True) -> int:
    if requested < 1 or requested > MAX_GPU_COUNT:
        raise ValueError(f"requested GPU count must be between 1 and {MAX_GPU_COUNT}")
    if not allow_partial and eligible_count < requested:
        return 0
    return min(requested, max(0, eligible_count), MAX_GPU_COUNT)


def profile_plan_for_count(count: int) -> ProfilePlan:
    if count < 0 or count > MAX_GPU_COUNT:
        raise ValueError(f"allocated GPU count must be between 0 and {MAX_GPU_COUNT}")
    plans = {
        0: ProfilePlan(fast=0, hq=0),
        1: ProfilePlan(fast=1, hq=0),
        2: ProfilePlan(fast=1, hq=1),
        3: ProfilePlan(fast=2, hq=1),
        4: ProfilePlan(fast=2, hq=2),
    }
    return plans[count]
