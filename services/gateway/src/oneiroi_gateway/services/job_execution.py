import asyncio
import json
import shutil
import subprocess
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from oneiroi_common.studio import GenerationDraft

ExecutionEvent = Callable[[str, int, dict[str, object]], Awaitable[None]]
CancelCheck = Callable[[], bool]


@dataclass(frozen=True, slots=True)
class JobExecutionResult:
    output_path: Path
    manifest_path: Path
    warm_start: bool
    metrics: dict[str, object]


class JobExecutor(Protocol):
    async def execute(
        self,
        job_id: str,
        draft: GenerationDraft,
        job_directory: Path,
        input_paths: tuple[Path | None, Path | None],
        on_event: ExecutionEvent,
        is_cancelled: CancelCheck,
    ) -> JobExecutionResult: ...


class FakeJobExecutor:
    async def execute(
        self,
        job_id: str,
        draft: GenerationDraft,
        job_directory: Path,
        input_paths: tuple[Path | None, Path | None],
        on_event: ExecutionEvent,
        is_cancelled: CancelCheck,
    ) -> JobExecutionResult:
        for phase, progress in (
            ("preparing", 25),
            ("prompt_encoding", 40),
            ("diffusion", 70),
            ("encoding", 92),
        ):
            if is_cancelled():
                raise asyncio.CancelledError
            await on_event(phase, progress, {})
            await asyncio.sleep(0.01)

        output = job_directory / "output" / "result.mp4"
        manifest = job_directory / "manifest.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        ffmpeg = shutil.which("ffmpeg")
        if ffmpeg is None:
            raise RuntimeError("ENCODING_FAILED: ffmpeg is unavailable")
        await asyncio.to_thread(
            subprocess.run,
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
                str(output),
            ],
            check=True,
        )
        manifest.write_text(
            json.dumps(
                {
                    "jobId": job_id,
                    "request": draft.model_dump(mode="json", by_alias=True),
                    "inputs": {
                        "firstFrame": input_paths[0] is not None,
                        "lastFrame": input_paths[1] is not None,
                    },
                    "output": {"mediaType": "video/mp4"},
                    "metrics": {"fake": True},
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return JobExecutionResult(
            output_path=output,
            manifest_path=manifest,
            warm_start=True,
            metrics={"fake": True},
        )
