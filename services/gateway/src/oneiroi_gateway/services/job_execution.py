import asyncio
import json
import shutil
import subprocess
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from oneiroi_common.generation import GenerationResult
from oneiroi_common.studio import GenerationDraft
from oneiroi_gateway.redis.control_streams import RedisDirectedStreams

ExecutionEvent = Callable[[str, int, dict[str, object]], Awaitable[None]]
CancelCheck = Callable[[], bool]


@dataclass(frozen=True, slots=True)
class JobExecutionContext:
    session_id: str
    attempt: int


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
        context: JobExecutionContext,
    ) -> JobExecutionResult: ...


class RedisJobExecutor:
    def __init__(self, streams: RedisDirectedStreams, *, timeout_seconds: float) -> None:
        self.streams = streams
        self.timeout_seconds = timeout_seconds

    async def execute(
        self,
        job_id: str,
        draft: GenerationDraft,
        job_directory: Path,
        input_paths: tuple[Path | None, Path | None],
        on_event: ExecutionEvent,
        is_cancelled: CancelCheck,
        context: JobExecutionContext,
    ) -> JobExecutionResult:
        del draft, input_paths, context
        cursor = "0-0"
        deadline = time.monotonic() + self.timeout_seconds
        cancel_path = job_directory / "control" / "cancel_requested"
        while True:
            if is_cancelled():
                cancel_path.parent.mkdir(parents=True, exist_ok=True)
                cancel_path.touch(exist_ok=True)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RuntimeError("RUNNER_JOB_TIMEOUT")
            events = await self.streams.read_job_events(
                job_id,
                cursor,
                block_milliseconds=max(1, int(min(remaining, 1) * 1000)),
            )
            for message_id, event_type, payload in events:
                cursor = message_id
                if event_type == "progress":
                    await on_event(
                        str(payload.get("phase", "generating")),
                        int(payload.get("progress", 0)),
                        dict(payload.get("details") or {}),
                    )
                elif event_type == "succeeded":
                    result = GenerationResult.model_validate(payload["result"])
                    result.validate_paths_within(job_directory)
                    return JobExecutionResult(
                        output_path=Path(result.output_path),
                        manifest_path=Path(result.manifest_path),
                        warm_start=result.warm_start,
                        metrics={
                            "elapsedSeconds": result.elapsed_seconds,
                            "peakVramMiB": result.peak_vram_mib,
                            "workerPid": result.worker_pid,
                        },
                    )
                elif event_type == "cancelled":
                    raise asyncio.CancelledError
                elif event_type == "failed":
                    code = str(payload.get("error") or "INFERENCE_FAILED")
                    message = str(payload.get("message") or code)
                    raise RuntimeError(f"{code}: {message}")


class FakeJobExecutor:
    async def execute(
        self,
        job_id: str,
        draft: GenerationDraft,
        job_directory: Path,
        input_paths: tuple[Path | None, Path | None],
        on_event: ExecutionEvent,
        is_cancelled: CancelCheck,
        context: JobExecutionContext,
    ) -> JobExecutionResult:
        del context
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
