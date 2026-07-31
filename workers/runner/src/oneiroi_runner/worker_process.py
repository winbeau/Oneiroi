import json
import os
import time
from multiprocessing.connection import Connection
from pathlib import Path
from typing import Any

from oneiroi_common.compute import PipelineSpec
from oneiroi_common.generation import GenerationResult, InternalI2VRequest
from oneiroi_runner.services.artifact_writer import ArtifactWriter
from oneiroi_runner.services.event_reporter import EventReporter


def _adapter(adapter_name: str) -> Any:
    if adapter_name == "fake":
        from oneiroi_runner.adapters.fake import FakePipelineAdapter

        return FakePipelineAdapter()
    if adapter_name == "ltx23-fast":
        from oneiroi_runner.adapters.ltx23_fast import Ltx23FastAdapter

        return Ltx23FastAdapter()
    raise ValueError(f"unknown adapter: {adapter_name}")


def _peak_vram_mib() -> int:
    try:
        import torch
    except ImportError:
        return 0
    if not torch.cuda.is_available():
        return 0
    return int(torch.cuda.max_memory_allocated() // (1024 * 1024))


def worker_process_main(
    connection: Connection,
    *,
    gpu_id: str,
    spec_payload: dict[str, object],
    adapter_name: str,
    storage_root: str,
) -> None:
    os.environ["CUDA_VISIBLE_DEVICES"] = gpu_id
    writer = ArtifactWriter(Path(storage_root))
    adapter = _adapter(adapter_name)
    spec = PipelineSpec.model_validate(spec_payload)
    started = time.perf_counter()

    try:
        connection.send({"type": "loading", "stage": "loading_checkpoint", "progress": 20})
        adapter.load(spec)
        connection.send({"type": "loading", "stage": "moving_weights_to_gpu", "progress": 75})
        adapter.warm_up()
        connection.send(
            {
                "type": "ready",
                "workerPid": os.getpid(),
                "adapterLoadCount": adapter.load_count,
                "loadSeconds": time.perf_counter() - started,
            }
        )

        while True:
            message = connection.recv()
            message_type = message.get("type")
            if message_type == "shutdown":
                adapter.close()
                connection.send({"type": "stopped", "workerPid": os.getpid()})
                return
            if message_type != "run":
                connection.send({"type": "failed", "error": "UNKNOWN_WORKER_COMMAND"})
                continue

            request = InternalI2VRequest.model_validate(message["request"])
            output_path, manifest_path, cancel_path = writer.prepare_job(request.job_id)
            cancel_path.unlink(missing_ok=True)
            reporter = EventReporter(connection.send)
            generation_started = time.perf_counter()

            def report_progress(
                phase: str,
                progress: int,
                details: dict[str, object],
                *,
                job_id: str = request.job_id,
                event_reporter: EventReporter = reporter,
            ) -> None:
                event_reporter.progress(job_id, phase, progress, details)

            try:
                payload = adapter.generate(
                    request,
                    output_path,
                    report_progress,
                    cancel_path.exists,
                )
                elapsed = time.perf_counter() - generation_started
                manifest = {
                    "jobId": request.job_id,
                    "pipelineSpec": spec.model_dump(mode="json", by_alias=True),
                    "request": request.model_dump(mode="json", by_alias=True),
                    "metrics": {
                        "elapsedSeconds": elapsed,
                        "peakVramMiB": _peak_vram_mib(),
                        "adapterLoadCount": adapter.load_count,
                    },
                    "adapter": payload,
                    "output": {"path": str(output_path), "mediaType": "video/mp4"},
                }
                manifest_path.write_text(
                    json.dumps(manifest, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                result = GenerationResult(
                    job_id=request.job_id,
                    output_path=str(output_path),
                    manifest_path=str(manifest_path),
                    elapsed_seconds=elapsed,
                    peak_vram_mib=_peak_vram_mib(),
                    worker_pid=os.getpid(),
                    warm_start=adapter.load_count == 1,
                )
                connection.send(
                    {
                        "type": "succeeded",
                        "result": result.model_dump(mode="json", by_alias=True),
                    }
                )
            except InterruptedError:
                connection.send({"type": "cancelled", "jobId": request.job_id})
            except Exception as exc:
                connection.send(
                    {
                        "type": "failed",
                        "jobId": request.job_id,
                        "error": type(exc).__name__,
                        "message": str(exc),
                    }
                )
    except Exception as exc:
        connection.send(
            {
                "type": "load_failed",
                "error": type(exc).__name__,
                "message": str(exc),
            }
        )
    finally:
        connection.close()
