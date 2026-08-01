import asyncio
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from oneiroi_bff.main import create_app as create_bff
from oneiroi_bff.settings import BffSettings
from oneiroi_common.compute import GpuInfo, GpuState
from oneiroi_gateway.main import create_app as create_gateway
from oneiroi_gateway.services.compute_sessions import ComputeSessionService, RecordingComputeBackend
from oneiroi_gateway.services.gpu_inventory import GpuInventoryService, InMemoryInventoryProvider
from oneiroi_gateway.services.job_execution import FakeJobExecutor
from oneiroi_gateway.settings import GatewaySettings


@pytest.mark.asyncio
async def test_bff_proxies_real_job_file_and_sse(tmp_path: Path) -> None:
    inventory = GpuInventoryService(
        InMemoryInventoryProvider(
            [
                GpuInfo(
                    id="GPU-bff-test",
                    physicalIndex=7,
                    name="H100",
                    vramTotalMiB=81_559,
                    state=GpuState.EMPTY,
                    eligible=True,
                )
            ]
        )
    )
    sessions = ComputeSessionService(inventory, RecordingComputeBackend())
    gateway = create_gateway(
        GatewaySettings(storage_root=tmp_path),
        inventory_service=inventory,
        compute_session_service=sessions,
        job_executor=FakeJobExecutor(),
    )
    bff = create_bff(BffSettings(gateway_base_url="http://gateway"), gateway_app=gateway)
    transport = ASGITransport(app=bff)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        conversation = await client.post("/v1/conversations", json={"title": "BFF"})
        compute = await client.post("/v1/compute/sessions", json={"requestedGpuCount": 1})
        created = await client.post(
            "/v1/jobs/i2v",
            json={
                "conversationId": conversation.json()["id"],
                "computeSessionId": compute.json()["id"],
                "draft": {"prompt": "proxied generation"},
            },
        )
        job_id = created.json()["id"]
        for _ in range(100):
            snapshot = await client.get(f"/v1/jobs/{job_id}")
            if snapshot.json()["stage"] == "succeeded":
                break
            await asyncio.sleep(0.02)
        video = await client.get(f"/v1/jobs/{job_id}/file")
        video_range = await client.get(
            f"/v1/jobs/{job_id}/file",
            headers={"Range": "bytes=0-31"},
        )
        events = await client.get(f"/v1/jobs/{job_id}/events")

    assert snapshot.json()["stage"] == "succeeded"
    assert video.headers["content-type"].startswith("video/mp4")
    assert b"ftyp" in video.content[:64]
    assert video_range.status_code == 206
    assert video_range.headers["content-range"].startswith("bytes 0-31/")
    assert len(video_range.content) == 32
    assert "event: job.succeeded" in events.text
