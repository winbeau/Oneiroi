import asyncio
import json
from pathlib import Path

import httpx

from oneiroi_common.studio import GenerationDraft
from oneiroi_gateway.gpu_server import (
    GpuServerClient,
    GpuServerInventoryProvider,
    GpuServerJobExecutor,
)
from oneiroi_gateway.services.job_execution import JobExecutionContext


class LeaseMapping:
    async def remote_lease_id(self, session_id: str) -> str:
        assert session_id == "compute-1"
        return "lease-remote"


def test_gpu_server_executor_uses_artifact_handles_and_downloads_result(tmp_path: Path) -> None:
    async def scenario() -> None:
        submitted: dict[str, object] = {}
        job_reads = 0

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal job_reads
            assert request.headers["x-icthub-client"] == "oneiroi"
            assert request.headers["authorization"] == "Bearer service-token"
            if request.url.path == "/internal/v1/gpus":
                return httpx.Response(
                    200,
                    json={
                        "gpus": [
                            {
                                "id": "GPU-remote",
                                "physicalIndex": 7,
                                "name": "H100",
                                "vramTotalMiB": 81559,
                                "vramUsedMiB": 0,
                                "eligible": True,
                            }
                        ]
                    },
                )
            if request.url.path == "/internal/v1/artifacts" and request.method == "POST":
                await request.aread()
                return httpx.Response(201, json={"id": "artifact-input"})
            if request.url.path == "/internal/v1/jobs" and request.method == "POST":
                submitted.update(json.loads(await request.aread()))
                assert request.headers["idempotency-key"] == "oneiroi-job-1-1"
                return httpx.Response(
                    202,
                    json={
                        "id": "remote-job",
                        "status": "queued",
                        "phase": None,
                        "progress": None,
                    },
                )
            if request.url.path == "/internal/v1/jobs/remote-job":
                job_reads += 1
                if job_reads == 1:
                    return httpx.Response(
                        200,
                        json={
                            "id": "remote-job",
                            "status": "running",
                            "phase": "stage-1",
                            "progress": 50,
                        },
                    )
                return httpx.Response(
                    200,
                    json={
                        "id": "remote-job",
                        "status": "succeeded",
                        "phase": "completed",
                        "progress": 100,
                        "profileId": "ltx23-distilled-fast-v1",
                        "result": [
                            {
                                "id": "artifact-output",
                                "mediaType": "video/mp4",
                                "sizeBytes": 9,
                                "sha256": "a" * 64,
                            }
                        ],
                    },
                )
            if request.url.path == "/internal/v1/artifacts/artifact-output":
                return httpx.Response(200, content=b"video-mp4")
            raise AssertionError(f"unexpected request: {request.method} {request.url}")

        client = GpuServerClient(
            "http://gpu-server",
            "service-token",
            timeout_seconds=10,
            transport=httpx.MockTransport(handler),
        )
        inventory = await GpuServerInventoryProvider(client).list_gpus()
        assert inventory[0].id == "GPU-remote"

        input_path = tmp_path / "input.png"
        input_path.write_bytes(b"png")
        events: list[tuple[str, int]] = []
        executor = GpuServerJobExecutor(client, LeaseMapping(), poll_seconds=0.001)
        result = await executor.execute(
            "job-1",
            GenerationDraft(
                prompt="a lake",
                firstFrameAssetId="asset-1",
            ),
            tmp_path / "job",
            (input_path, None),
            lambda phase, progress, _details: _event(events, phase, progress),
            lambda: False,
            JobExecutionContext(session_id="compute-1", attempt=1),
        )

        assert submitted["leaseId"] == "lease-remote"
        assert submitted["inputs"]["firstFrameArtifactId"] == "artifact-input"
        assert "path" not in str(submitted).lower()
        assert result.output_path.read_bytes() == b"video-mp4"
        assert result.manifest_path.is_file()
        assert events[-1] == ("stage-1", 50)
        await client.close()

    asyncio.run(scenario())


async def _event(events: list[tuple[str, int]], phase: str, progress: int) -> None:
    events.append((phase, progress))
