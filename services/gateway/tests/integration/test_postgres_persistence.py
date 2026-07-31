import asyncio
import os
from pathlib import Path
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from oneiroi_common.compute import GpuInfo, GpuState
from oneiroi_gateway.main import create_app
from oneiroi_gateway.services.compute_sessions import ComputeSessionService, RecordingComputeBackend
from oneiroi_gateway.services.gpu_inventory import GpuInventoryService, InMemoryInventoryProvider
from oneiroi_gateway.services.job_execution import FakeJobExecutor
from oneiroi_gateway.settings import GatewaySettings

pytestmark = pytest.mark.skipif(
    os.getenv("ONEIROI_TEST_POSTGRES") != "1",
    reason="set ONEIROI_TEST_POSTGRES=1 for the loopback PostgreSQL integration test",
)

DATABASE_URL = os.getenv(
    "ONEIROI_GATEWAY_DATABASE_URL",
    "postgresql+asyncpg://oneiroi:oneiroi-local@127.0.0.1:5432/oneiroi",
)


def components():
    inventory = GpuInventoryService(
        InMemoryInventoryProvider(
            [
                GpuInfo(
                    id="GPU-postgres-test",
                    physicalIndex=0,
                    name="H100",
                    vramTotalMiB=81_559,
                    state=GpuState.EMPTY,
                    eligible=True,
                )
            ]
        )
    )
    return inventory, ComputeSessionService(inventory, RecordingComputeBackend())


@pytest.mark.asyncio
async def test_job_and_events_survive_gateway_recreation(tmp_path: Path) -> None:
    owner = f"postgres-{uuid4().hex}"
    inventory, sessions = components()
    settings = GatewaySettings(
        persistence_enabled=True,
        database_url=DATABASE_URL,
        storage_root=tmp_path,
    )
    first_app = create_app(
        settings,
        inventory_service=inventory,
        compute_session_service=sessions,
        job_executor=FakeJobExecutor(),
    )
    first_transport = ASGITransport(app=first_app)
    async with AsyncClient(transport=first_transport, base_url="http://test") as client:
        headers = {"X-Oneiroi-User": owner}
        conversation = await client.post(
            "/v1/conversations",
            headers=headers,
            json={"title": "Persistent"},
        )
        compute = await client.post(
            "/v1/compute/sessions",
            headers=headers,
            json={"requestedGpuCount": 1},
        )
        created = await client.post(
            "/v1/jobs/i2v",
            headers=headers,
            json={
                "conversationId": conversation.json()["id"],
                "computeSessionId": compute.json()["id"],
                "draft": {"prompt": "persist this job"},
            },
        )
        job_id = created.json()["id"]
        for _ in range(100):
            snapshot = await client.get(f"/v1/jobs/{job_id}", headers=headers)
            if snapshot.json()["stage"] == "succeeded":
                break
            await asyncio.sleep(0.02)
        assert snapshot.json()["stage"] == "succeeded"
    await first_app.state.database_engine.dispose()

    second_inventory, second_sessions = components()
    second_app = create_app(
        settings,
        inventory_service=second_inventory,
        compute_session_service=second_sessions,
    )
    second_transport = ASGITransport(app=second_app)
    async with AsyncClient(transport=second_transport, base_url="http://test") as client:
        headers = {"X-Oneiroi-User": owner}
        restored_job = await client.get(f"/v1/jobs/{job_id}", headers=headers)
        restored_conversations = await client.get("/v1/conversations", headers=headers)

    assert restored_job.json()["stage"] == "succeeded"
    assert restored_conversations.json()[0]["title"] == "Persistent"

    engine = second_app.state.database_engine
    async with engine.begin() as connection:
        for statement in (
            "DELETE FROM job_events WHERE owner_id = :owner",
            "DELETE FROM job_attempts WHERE job_id IN "
            "(SELECT id FROM jobs WHERE owner_id = :owner)",
            "DELETE FROM jobs WHERE owner_id = :owner",
            "DELETE FROM assets WHERE owner_id = :owner",
            "DELETE FROM conversations WHERE owner_id = :owner",
        ):
            await connection.execute(text(statement), {"owner": owner})
    await engine.dispose()
