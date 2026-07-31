import json
import shutil
import subprocess
import time
from pathlib import Path

from oneiroi_common.compute import PipelineSpec
from oneiroi_common.generation import InternalI2VRequest
from oneiroi_runner.adapters.base import CancelCheck, ProgressCallback


class FakePipelineAdapter:
    def __init__(self) -> None:
        self.load_count = 0
        self.spec: PipelineSpec | None = None

    def load(self, spec: PipelineSpec) -> None:
        self.spec = spec
        self.load_count += 1

    def warm_up(self) -> None:
        if self.spec is None:
            raise RuntimeError("pipeline is not loaded")

    def generate(
        self,
        request: InternalI2VRequest,
        output_path: Path,
        progress: ProgressCallback,
        is_cancelled: CancelCheck,
    ) -> dict[str, object]:
        for phase, percentage in (
            ("preparing", 20),
            ("prompt_encoding", 35),
            ("diffusion", 70),
            ("encoding", 90),
        ):
            if is_cancelled():
                raise InterruptedError("generation cancelled")
            progress(phase, percentage, {})
            time.sleep(0.01)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        ffmpeg = shutil.which("ffmpeg")
        if ffmpeg:
            subprocess.run(
                [
                    ffmpeg,
                    "-loglevel",
                    "error",
                    "-f",
                    "lavfi",
                    "-i",
                    "color=c=black:s=64x64:r=8:d=0.25",
                    "-an",
                    "-c:v",
                    "libx264",
                    "-pix_fmt",
                    "yuv420p",
                    "-movflags",
                    "+faststart",
                    "-y",
                    str(output_path),
                ],
                check=True,
            )
        else:
            output_path.write_bytes(b"fake-mp4")

        return {
            "profileId": self.spec.profile_id if self.spec else "fake",
            "request": request.model_dump(mode="json", by_alias=True),
            "adapterLoadCount": self.load_count,
        }

    def close(self) -> None:
        self.spec = None


def write_manifest(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
