import pytest
from httpx import ASGITransport, AsyncClient

from oneiroi_common.compute import GpuInfo, GpuState
from oneiroi_gateway.main import create_app
from oneiroi_gateway.services.compute_sessions import (
    ComputeSessionService,
    RecordingComputeBackend,
)
from oneiroi_gateway.services.gpu_inventory import GpuInventoryService, InMemoryInventoryProvider
from oneiroi_gateway.settings import GatewaySettings


@pytest.fixture
def compute_app():
    inventory = GpuInventoryService(
        InMemoryInventoryProvider(
            [
                GpuInfo(
                    id="GPU-fast-ready",
                    physicalIndex=7,
                    name="NVIDIA H100 80GB HBM3",
                    vramTotalMiB=81_559,
                    eligible=True,
                    state=GpuState.EMPTY,
                )
            ]
        )
    )
    backend = RecordingComputeBackend()
    sessions = ComputeSessionService(inventory, backend)
    return create_app(
        GatewaySettings(),
        inventory_service=inventory,
        compute_session_service=sessions,
    ), backend


@pytest.mark.asyncio
async def test_one_gpu_session_loads_fast_and_releases(compute_app, caplog) -> None:
    caplog.set_level("INFO", logger="oneiroi.audit")
    app, backend = compute_app
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        created = await client.post(
            "/v1/compute/sessions",
            headers={"Idempotency-Key": "one-card"},
            json={
                "requestedGpuCount": 1,
                "selectionMode": "auto",
                "gpuIds": [],
                "profilePolicy": "balanced",
                "allowPartial": True,
            },
        )
        assert created.status_code == 202
        body = created.json()
        assert body["state"] == "ready"
        assert body["profilePlan"] == {"fast": 1, "hq": 0}
        assert body["slots"][0]["physicalIndex"] == 7
        session_id = body["id"]

        snapshot = await client.get(f"/v1/compute/sessions/{session_id}")
        assert snapshot.json()["slots"][0]["state"] == "ready"

        released = await client.post(
            f"/v1/compute/sessions/{session_id}/release",
            json={"policy": "when_idle"},
        )
        assert released.json()["state"] == "released"

    assert len(backend.loaded) == 1
    assert len(backend.released) == 1
    audit_messages = [record.message for record in caplog.records if record.name == "oneiroi.audit"]
    assert any("action=compute.create" in message for message in audit_messages)
    assert any("action=compute.release" in message for message in audit_messages)
    assert all("demo-user" not in message for message in audit_messages)


@pytest.mark.asyncio
async def test_session_idempotency_rejects_payload_mismatch(compute_app) -> None:
    app, _ = compute_app
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        first = await client.post(
            "/v1/compute/sessions",
            headers={"Idempotency-Key": "same"},
            json={"requestedGpuCount": 1},
        )
        repeated = await client.post(
            "/v1/compute/sessions",
            headers={"Idempotency-Key": "same"},
            json={"requestedGpuCount": 1},
        )
        mismatch = await client.post(
            "/v1/compute/sessions",
            headers={"Idempotency-Key": "same"},
            json={"requestedGpuCount": 2},
        )

    assert first.json()["id"] == repeated.json()["id"]
    assert mismatch.status_code == 409
    assert mismatch.json()["detail"] == "IDEMPOTENCY_KEY_REUSED"


@pytest.mark.asyncio
async def test_session_owner_isolation(compute_app) -> None:
    app, _ = compute_app
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        created = await client.post("/v1/compute/sessions", json={"requestedGpuCount": 1})
        hidden = await client.get(
            f"/v1/compute/sessions/{created.json()['id']}",
            headers={"X-Oneiroi-User": "another-user"},
        )

    assert hidden.status_code == 404
