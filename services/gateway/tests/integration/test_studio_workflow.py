import asyncio
import io
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from PIL import Image

from oneiroi_common.compute import GpuInfo, GpuState
from oneiroi_gateway.main import create_app
from oneiroi_gateway.routes.jobs import _public_manifest
from oneiroi_gateway.services.compute_sessions import ComputeSessionService, RecordingComputeBackend
from oneiroi_gateway.services.gpu_inventory import GpuInventoryService, InMemoryInventoryProvider
from oneiroi_gateway.services.job_execution import FakeJobExecutor
from oneiroi_gateway.settings import GatewaySettings


def png_bytes() -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (64, 64), color=(30, 40, 50)).save(output, format="PNG")
    return output.getvalue()


@pytest.mark.asyncio
async def test_malformed_png_returns_validation_error(tmp_path: Path) -> None:
    app = workflow_app(tmp_path)
    transport = ASGITransport(app=app)
    malformed_png = bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
        "0000000d49444154789c6360f8cfc0000004010100f41c2fa50000000049454e44"
        "ae426082"
    )

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/v1/uploads/images",
            files={"file": ("malformed.png", malformed_png, "image/png")},
        )

    assert response.status_code == 422
    assert response.json()["detail"] == "INVALID_IMAGE"


def test_public_manifest_removes_path_bearing_fields() -> None:
    manifest = _public_manifest(
        {
            "checkpointPath": "/models/checkpoint.safetensors",
            "pipelineSpec": {
                "loraPathsAndScales": [["/models/lora.safetensors", 1.0]],
                "profileId": "fast",
            },
        }
    )

    assert manifest == {"pipelineSpec": {"profileId": "fast"}}


class FailingDispatcher:
    async def dispatch(self, reservation, job_id, payload) -> None:
        del reservation, job_id, payload
        raise RuntimeError("REDIS_UNAVAILABLE")


def workflow_app(tmp_path: Path, *, execute: bool = True, job_dispatcher=None):
    inventory = GpuInventoryService(
        InMemoryInventoryProvider(
            [
                GpuInfo(
                    id=f"GPU-workflow-{index}",
                    physicalIndex=index,
                    name="NVIDIA H100 80GB HBM3",
                    vramTotalMiB=81_559,
                    state=GpuState.EMPTY,
                    eligible=True,
                )
                for index in range(2)
            ]
        )
    )
    sessions = ComputeSessionService(inventory, RecordingComputeBackend())
    app = create_app(
        GatewaySettings(storage_root=tmp_path),
        inventory_service=inventory,
        compute_session_service=sessions,
        job_executor=FakeJobExecutor() if execute else None,
        job_dispatcher=job_dispatcher,
    )
    return app


@pytest.mark.asyncio
async def test_conversation_upload_job_sse_and_real_mp4(tmp_path: Path) -> None:
    app = workflow_app(tmp_path)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        conversation = await client.post("/v1/conversations", json={"title": "Workflow"})
        conversation_id = conversation.json()["id"]
        first_put = await client.put(
            f"/v1/conversations/{conversation_id}",
            json={"title": "Workflow updated"},
        )
        repeated_put = await client.put(
            f"/v1/conversations/{conversation_id}",
            json={"title": "Workflow updated"},
        )
        assert first_put.json()["id"] == repeated_put.json()["id"] == conversation_id
        assert len((await client.get("/v1/conversations")).json()) == 1

        session = await client.post("/v1/compute/sessions", json={"requestedGpuCount": 1})
        session_id = session.json()["id"]
        uploaded = await client.post(
            "/v1/uploads/images",
            files={"file": ("frame.png", png_bytes(), "image/png")},
            data={"title": "首帧"},
        )
        assert uploaded.status_code == 201
        asset_id = uploaded.json()["id"]

        created = await client.post(
            "/v1/jobs/i2v",
            json={
                "conversationId": conversation_id,
                "computeSessionId": session_id,
                "draft": {
                    "prompt": "A cinematic transition",
                    "firstFrameAssetId": asset_id,
                },
            },
        )
        assert created.status_code == 202
        job_id = created.json()["id"]

        for _ in range(100):
            snapshot = await client.get(f"/v1/jobs/{job_id}")
            if snapshot.json()["stage"] in {"succeeded", "failed"}:
                break
            await asyncio.sleep(0.02)
        assert snapshot.json()["stage"] == "succeeded"
        assert snapshot.json()["output"]["mediaType"] == "video/mp4"

        video = await client.get(f"/v1/jobs/{job_id}/file")
        manifest = await client.get(f"/v1/jobs/{job_id}/manifest")
        events = await client.get(f"/v1/jobs/{job_id}/events")
        hidden = await client.get(
            f"/v1/jobs/{job_id}/file",
            headers={"X-Oneiroi-User": "another-user"},
        )

    assert video.status_code == 200
    assert video.headers["content-type"].startswith("video/mp4")
    assert b"ftyp" in video.content[:64]
    assert manifest.status_code == 200
    assert manifest.json()["jobId"] == job_id
    assert "path" not in manifest.text.lower()
    assert hidden.status_code == 404
    assert "event: job.succeeded" in events.text
    assert "event: job.updated" in events.text
    attempts = await app.state.repository.list_attempts(job_id)
    assert attempts[0].status == "succeeded"
    assert attempts[0].finished_at is not None


@pytest.mark.asyncio
async def test_one_card_hq_job_is_rejected_by_backend(tmp_path: Path) -> None:
    app = workflow_app(tmp_path)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        conversation = await client.post("/v1/conversations", json={"title": "HQ"})
        session = await client.post("/v1/compute/sessions", json={"requestedGpuCount": 1})
        response = await client.post(
            "/v1/jobs/i2v",
            json={
                "conversationId": conversation.json()["id"],
                "computeSessionId": session.json()["id"],
                "draft": {
                    "prompt": "HQ attempt",
                    "queue": "hq",
                    "profile": "hq",
                    "resolution": "1080p",
                },
            },
        )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "HQ_REQUIRES_AT_LEAST_2_GPUS"


@pytest.mark.asyncio
async def test_dispatch_failure_is_persisted_and_releases_slot(tmp_path: Path) -> None:
    app = workflow_app(tmp_path, execute=False, job_dispatcher=FailingDispatcher())
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        conversation = await client.post("/v1/conversations", json={"title": "Failure"})
        session = await client.post("/v1/compute/sessions", json={"requestedGpuCount": 1})
        created = await client.post(
            "/v1/jobs/i2v",
            json={
                "conversationId": conversation.json()["id"],
                "computeSessionId": session.json()["id"],
                "draft": {"prompt": "dispatch failure"},
            },
        )
        jobs = await client.get("/v1/jobs")

    assert created.status_code == 409
    assert jobs.json()[0]["stage"] == "failed"
    assert jobs.json()[0]["error"]["code"] == "DISPATCH_FAILED"
    session_snapshot = app.state.job_service.sessions.sessions[session.json()["id"]]
    assert session_snapshot.slots[0].state is GpuState.READY


@pytest.mark.asyncio
async def test_cancel_and_retry_create_new_attempt(tmp_path: Path) -> None:
    app = workflow_app(tmp_path, execute=False)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        conversation = await client.post("/v1/conversations", json={"title": "Retry"})
        session = await client.post("/v1/compute/sessions", json={"requestedGpuCount": 1})
        created = await client.post(
            "/v1/jobs/i2v",
            json={
                "conversationId": conversation.json()["id"],
                "computeSessionId": session.json()["id"],
                "draft": {"prompt": "retry me"},
            },
        )
        job_id = created.json()["id"]
        cancelled = await client.post(f"/v1/jobs/{job_id}/cancel")
        retried = await client.post(f"/v1/jobs/{job_id}/retry")

    assert cancelled.json()["stage"] == "cancelled"
    assert retried.json()["attempt"] == 2
    attempts = await app.state.repository.list_attempts(job_id)
    assert [attempt.attempt for attempt in attempts] == [1, 2]
