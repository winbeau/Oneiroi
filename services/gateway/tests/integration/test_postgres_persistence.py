import asyncio
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from oneiroi_common.agent import AgentMessageContent, AgentRunResponse, AgentRunStatus
from oneiroi_common.compute import ComputeSessionCreate, ComputeSessionRelease, GpuInfo, GpuState
from oneiroi_gateway.agent.fake import FakeAgentProvider
from oneiroi_gateway.agent.protocol import ProviderEvent, ProviderEventType
from oneiroi_gateway.agent.runtime import AgentRuntime
from oneiroi_gateway.db.session import create_engine, create_session_factory
from oneiroi_gateway.main import create_app
from oneiroi_gateway.redis.leases import InMemoryLeaseStore
from oneiroi_gateway.repositories.agent import AgentStateConflict, StoredAgentRun
from oneiroi_gateway.repositories.compute import SqlComputeStateRepository
from oneiroi_gateway.repositories.sql_agent import SqlAgentRepository
from oneiroi_gateway.repositories.sql_studio import SqlStudioRepository
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


def postgres_stored_run(
    owner_id: str,
    thread_id: str,
    conversation_id: str,
    *,
    run_id: str,
    key: str,
) -> StoredAgentRun:
    return StoredAgentRun(
        owner_id=owner_id,
        idempotency_key=key,
        request_hash=key.ljust(64, "0")[:64],
        response=AgentRunResponse(
            id=run_id,
            threadId=thread_id,
            conversationId=conversation_id,
            status=AgentRunStatus.QUEUED,
            model="fake-model",
            provider="fake",
            transport="sse",
            reasoningEffort="high",
            promptVersion="oneiroi-agent-v1",
            toolsetVersion="oneiroi-tools-v1",
            inputSnapshot={"draftSnapshot": {"prompt": "lake"}},
            createdAt=datetime.now(UTC),
        ),
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
async def test_active_compute_session_restores_with_live_lease() -> None:
    owner = f"compute-postgres-{uuid4().hex}"
    inventory, _ = components()
    engine = create_engine(DATABASE_URL)
    state_repository = SqlComputeStateRepository(create_session_factory(engine))
    leases = InMemoryLeaseStore()
    first = ComputeSessionService(
        inventory,
        RecordingComputeBackend(),
        leases=leases,
        state_repository=state_repository,
    )
    created = await first.create(owner, ComputeSessionCreate(requestedGpuCount=1))
    await first.close()

    second = ComputeSessionService(
        inventory,
        RecordingComputeBackend(),
        leases=leases,
        state_repository=state_repository,
    )
    restored = await second.restore()

    assert restored == [created.id]
    assert second.get(owner, created.id).slots[0].state is GpuState.READY
    assert second.fencing_token(created.slots[0].id)
    await second.release(owner, created.id, ComputeSessionRelease())
    await second.close()

    async with engine.begin() as connection:
        await connection.execute(
            text(
                "DELETE FROM gpu_slots WHERE compute_session_id IN "
                "(SELECT id FROM compute_sessions WHERE owner_id = :owner)"
            ),
            {"owner": owner},
        )
        await connection.execute(
            text("DELETE FROM compute_sessions WHERE owner_id = :owner"),
            {"owner": owner},
        )
    await engine.dispose()


@pytest.mark.asyncio
async def test_agent_migration_roundtrip_preserves_existing_conversations() -> None:
    gateway_dir = Path(__file__).resolve().parents[2]
    environment = os.environ | {"ONEIROI_GATEWAY_DATABASE_URL": DATABASE_URL}
    owner = f"agent-migration-{uuid4().hex}"

    subprocess.run(
        ["uv", "run", "alembic", "-c", "alembic.ini", "downgrade", "0001_dynamic_backend"],
        cwd=gateway_dir,
        env=environment,
        check=True,
    )
    try:
        engine = create_engine(DATABASE_URL)
        studio = SqlStudioRepository(create_session_factory(engine))
        conversation = await studio.create_conversation(owner, "Migration survivor")
        assert (await studio.get_conversation(owner, conversation.id)).title == "Migration survivor"
        await engine.dispose()

        subprocess.run(
            ["uv", "run", "alembic", "-c", "alembic.ini", "upgrade", "head"],
            cwd=gateway_dir,
            env=environment,
            check=True,
        )
        engine = create_engine(DATABASE_URL)
        studio = SqlStudioRepository(create_session_factory(engine))
        assert (await studio.get_conversation(owner, conversation.id)).title == "Migration survivor"
        async with engine.begin() as connection:
            await connection.execute(
                text("DELETE FROM conversations WHERE owner_id = :owner"), {"owner": owner}
            )
        await engine.dispose()
    finally:
        subprocess.run(
            ["uv", "run", "alembic", "-c", "alembic.ini", "upgrade", "head"],
            cwd=gateway_dir,
            env=environment,
            check=True,
        )


@pytest.mark.asyncio
async def test_agent_database_enforces_concurrency_cas_and_owner_relationships() -> None:
    owner = f"agent-constraints-{uuid4().hex}"
    other_owner = f"{owner}-other"
    engine = create_engine(DATABASE_URL)
    sessions = create_session_factory(engine)
    studio = SqlStudioRepository(sessions)
    first_repository = SqlAgentRepository(sessions)
    second_repository = SqlAgentRepository(sessions)
    conversation = await studio.create_conversation(owner, "Agent constraints")
    thread = await first_repository.get_or_create_thread(owner, conversation.id, "oneiroi-agent-v1")
    first_run = postgres_stored_run(
        owner,
        thread.id,
        conversation.id,
        run_id=f"agent-run-{uuid4().hex}",
        key=f"first-{uuid4().hex}",
    )
    second_run = postgres_stored_run(
        owner,
        thread.id,
        conversation.id,
        run_id=f"agent-run-{uuid4().hex}",
        key=f"second-{uuid4().hex}",
    )
    results = await asyncio.gather(
        first_repository.create_run(first_run, AgentMessageContent(text="first")),
        second_repository.create_run(second_run, AgentMessageContent(text="second")),
        return_exceptions=True,
    )
    created = [result for result in results if isinstance(result, tuple)]
    rejected = [result for result in results if isinstance(result, RuntimeError)]
    assert len(created) == 1
    assert len(rejected) == 1
    assert str(rejected[0]) == "AGENT_RUN_CONCURRENCY_LIMIT"

    active = created[0][0]
    stale = await second_repository.get_run(owner, active.response.id)
    cancelling = await first_repository.get_run(owner, active.response.id)
    cancelling.response = cancelling.response.model_copy(
        update={"status": AgentRunStatus.CANCELLING}
    )
    await first_repository.transition_run(
        cancelling,
        "agent.run.cancelling",
        {"status": "cancelling"},
        frozenset({AgentRunStatus.QUEUED}),
    )
    stale.response = stale.response.model_copy(update={"status": AgentRunStatus.STREAMING})
    with pytest.raises(AgentStateConflict) as exc_info:
        await second_repository.transition_run(
            stale,
            "agent.run.started",
            {"status": "streaming"},
            frozenset({AgentRunStatus.QUEUED}),
        )
    assert exc_info.value.latest.response.status is AgentRunStatus.CANCELLING

    other_conversation = await studio.create_conversation(owner, "Other conversation")
    with pytest.raises(IntegrityError):
        async with engine.begin() as connection:
            await connection.execute(
                text("UPDATE agent_runs SET conversation_id = :conversation WHERE id = :run_id"),
                {"conversation": other_conversation.id, "run_id": active.response.id},
            )

    cancelling.response = cancelling.response.model_copy(
        update={"status": AgentRunStatus.CANCELLED, "finished_at": datetime.now(UTC)}
    )
    await first_repository.transition_run(
        cancelling,
        "agent.run.cancelled",
        {"status": "cancelled"},
        frozenset({AgentRunStatus.CANCELLING}),
    )
    waiting_run, waiting_created = await first_repository.create_run(
        postgres_stored_run(
            owner,
            thread.id,
            conversation.id,
            run_id=f"agent-run-{uuid4().hex}",
            key=f"waiting-{uuid4().hex}",
        ),
        AgentMessageContent(text="waiting"),
    )
    assert waiting_created is True
    waiting_run.response = waiting_run.response.model_copy(
        update={"status": AgentRunStatus.STREAMING}
    )
    await first_repository.transition_run(
        waiting_run,
        "agent.run.started",
        {"status": "streaming"},
        frozenset({AgentRunStatus.QUEUED}),
    )
    waiting_run.response = waiting_run.response.model_copy(
        update={"status": AgentRunStatus.WAITING_APPROVAL}
    )
    await first_repository.transition_run(
        waiting_run,
        "agent.run.waiting_approval",
        {"status": "waiting_approval"},
        frozenset({AgentRunStatus.STREAMING}),
    )
    recovery_runtime = AgentRuntime(first_repository, studio, None, GatewaySettings(_env_file=None))
    assert await recovery_runtime.recover_incomplete() == [waiting_run.response.id]
    recovered = await first_repository.get_run(owner, waiting_run.response.id)
    assert recovered.response.status is AgentRunStatus.FAILED
    _, post_recovery_created = await second_repository.create_run(
        postgres_stored_run(
            owner,
            thread.id,
            conversation.id,
            run_id=f"agent-run-{uuid4().hex}",
            key=f"post-recovery-{uuid4().hex}",
        ),
        AgentMessageContent(text="after recovery"),
    )
    assert post_recovery_created is True

    with pytest.raises(IntegrityError):
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO agent_threads "
                    "(id, owner_id, conversation_id, status, summary_cursor, "
                    "prompt_version, created_at, updated_at) VALUES "
                    "(:id, :owner, :conversation, 'active', 0, 'v1', now(), now())"
                ),
                {
                    "id": f"agent-thread-{uuid4().hex}",
                    "owner": other_owner,
                    "conversation": conversation.id,
                },
            )

    async with engine.begin() as connection:
        for statement in (
            "DELETE FROM agent_events WHERE owner_id = :owner",
            "DELETE FROM agent_messages WHERE owner_id = :owner",
            "DELETE FROM agent_runs WHERE owner_id = :owner",
            "DELETE FROM agent_threads WHERE owner_id = :owner",
            "DELETE FROM conversations WHERE owner_id = :owner",
        ):
            await connection.execute(text(statement), {"owner": owner})
    await engine.dispose()


@pytest.mark.asyncio
async def test_agent_thread_run_messages_and_events_survive_gateway_recreation(
    tmp_path: Path,
) -> None:
    owner = f"agent-postgres-{uuid4().hex}"
    provider = FakeAgentProvider(
        events=[
            ProviderEvent(
                event_type=ProviderEventType.TEXT_DELTA,
                data={
                    "delta": '{"text":"persisted","draftProposal":{"prompt":"persistent proposal"}}'
                },
            ),
            ProviderEvent(event_type=ProviderEventType.RESPONSE_COMPLETED),
        ]
    )
    settings = GatewaySettings(
        _env_file=None,
        persistence_enabled=True,
        database_url=DATABASE_URL,
        storage_root=tmp_path,
    )
    inventory, sessions = components()
    first_app = create_app(
        settings,
        inventory_service=inventory,
        compute_session_service=sessions,
        agent_provider=provider,
    )
    async with AsyncClient(
        transport=ASGITransport(app=first_app), base_url="http://test"
    ) as client:
        headers = {"X-Oneiroi-User": owner}
        conversation = await client.post(
            "/v1/conversations", headers=headers, json={"title": "Persistent Agent"}
        )
        created = await client.post(
            "/v1/agent/runs",
            headers={**headers, "Idempotency-Key": "postgres-agent-1"},
            json={
                "conversationId": conversation.json()["id"],
                "message": "persist this",
                "draftSnapshot": {"prompt": "lake"},
            },
        )
        run_id = created.json()["id"]
        for _ in range(100):
            snapshot = await client.get(f"/v1/agent/runs/{run_id}", headers=headers)
            if snapshot.json()["status"] == "completed":
                break
            await asyncio.sleep(0.02)
        assert snapshot.json()["status"] == "completed"
        thread_id = snapshot.json()["threadId"]
    await first_app.state.agent_runtime.close()
    await first_app.state.database_engine.dispose()

    second_inventory, second_sessions = components()
    second_app = create_app(
        settings,
        inventory_service=second_inventory,
        compute_session_service=second_sessions,
    )
    async with AsyncClient(
        transport=ASGITransport(app=second_app), base_url="http://test"
    ) as client:
        headers = {"X-Oneiroi-User": owner}
        restored_run = await client.get(f"/v1/agent/runs/{run_id}", headers=headers)
        restored_messages = await client.get(
            f"/v1/agent/threads/{thread_id}/messages", headers=headers
        )
        restored_events = await client.get(f"/v1/agent/runs/{run_id}/events", headers=headers)
        hidden = await client.get(
            f"/v1/agent/runs/{run_id}", headers={"X-Oneiroi-User": f"{owner}-other"}
        )
    assert restored_run.json()["status"] == "completed"
    assert restored_messages.json()[-1]["content"]["draftProposal"]["prompt"] == (
        "persistent proposal"
    )
    assert "agent.run.completed" in restored_events.text
    assert hidden.status_code == 404

    engine = second_app.state.database_engine
    async with engine.begin() as connection:
        for statement in (
            "DELETE FROM agent_events WHERE owner_id = :owner",
            "DELETE FROM agent_approvals WHERE owner_id = :owner",
            "DELETE FROM agent_tool_calls WHERE owner_id = :owner",
            "DELETE FROM agent_messages WHERE owner_id = :owner",
            "DELETE FROM agent_runs WHERE owner_id = :owner",
            "DELETE FROM agent_threads WHERE owner_id = :owner",
            "DELETE FROM conversations WHERE owner_id = :owner",
        ):
            await connection.execute(text(statement), {"owner": owner})
    await second_app.state.agent_runtime.close()
    await engine.dispose()


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
