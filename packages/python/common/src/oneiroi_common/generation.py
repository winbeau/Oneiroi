from pathlib import Path
from typing import Annotated

from pydantic import Field, field_validator

from oneiroi_common.compute import ContractModel, ProfileTier


class InternalI2VRequest(ContractModel):
    job_id: str
    prompt: Annotated[str, Field(min_length=1, max_length=4_000)]
    negative_prompt: str = ""
    profile: ProfileTier = ProfileTier.FAST
    width: Annotated[int, Field(default=768, ge=64)]
    height: Annotated[int, Field(default=512, ge=64)]
    num_frames: Annotated[int, Field(default=9, ge=1)]
    frame_rate: Annotated[float, Field(default=24, gt=0)]
    seed: int = 42
    enhance_prompt: bool = False
    first_frame_path: str | None = None
    last_frame_path: str | None = None
    first_frame_strength: Annotated[float, Field(default=1, ge=0, le=1)]
    last_frame_strength: Annotated[float, Field(default=1, ge=0, le=1)]

    @field_validator("width", "height")
    @classmethod
    def dimensions_must_be_model_aligned(cls, value: int) -> int:
        if value % 64:
            raise ValueError("LTX dimensions must be divisible by 64")
        return value

    @field_validator("num_frames")
    @classmethod
    def frames_must_follow_eight_k_plus_one(cls, value: int) -> int:
        if (value - 1) % 8:
            raise ValueError("LTX frame count must satisfy 8K+1")
        return value


class GenerationResult(ContractModel):
    job_id: str
    output_path: str
    manifest_path: str
    elapsed_seconds: float = Field(ge=0)
    peak_vram_mib: int = Field(default=0, ge=0, alias="peakVramMiB")
    worker_pid: int
    warm_start: bool

    def validate_paths_within(self, root: Path) -> None:
        output = Path(self.output_path).resolve()
        manifest = Path(self.manifest_path).resolve()
        resolved_root = root.resolve()
        if not output.is_relative_to(resolved_root) or not manifest.is_relative_to(resolved_root):
            raise ValueError("worker artifact escaped the assigned storage root")
