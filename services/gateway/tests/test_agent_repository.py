from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.dialects import sqlite
from sqlalchemy.schema import CreateIndex

from oneiroi_common.agent import (
    AgentMessageContent,
    AgentRunResponse,
    AgentRunStatus,
)
from oneiroi_gateway.db.models.agent import AgentRunModel
from oneiroi_gateway.repositories.agent import (
    AgentExecutionOwned,
    AgentStateConflict,
    InMemoryAgentRepository,
    StoredAgentRun,
)


def stored_run(
    owner: str,
    thread_id: str,
    *,
    run_id: str,
    key: str,
    request_hash: str,
) -> StoredAgentRun:
    return StoredAgentRun(
        owner_id=owner,
        idempotency_key=key,
        request_hash=request_hash,
        response=AgentRunResponse(
            id=run_id,
            threadId=thread_id,
            conversationId="conversation-1",
            status=AgentRunStatus.QUEUED,
            model="fake-model",
            provider="fake",
            transport="sse",
            reasoningEffort="high",
            promptVersion="prompt-v1",
            toolsetVersion="tools-v1",
            inputSnapshot={"draftSnapshot": {"prompt": "lake"}},
            createdAt=datetime.now(UTC),
        ),
    )


@pytest.mark.asyncio
async def test_execution_renew_requires_live_lease_and_state_updates_preserve_renewal() -> None:
    repository = InMemoryAgentRepository()
    thread = await repository.get_or_create_thread("owner-a", "conversation-1", "prompt-v1")
    run = stored_run(
        "owner-a",
        thread.id,
        run_id="agent-run-lease",
        key="lease-key",
        request_hash="a" * 64,
    )
    run.executor_id = "executor-a"
    run.execution_lease_expires_at = datetime.now(UTC) + timedelta(seconds=30)
    run, _ = await repository.create_run(run, AgentMessageContent(text="lease"))
    stale = await repository.get_run("owner-a", run.response.id)
    renewed_expiry = datetime.now(UTC) + timedelta(seconds=90)
    await repository.renew_run_execution("owner-a", run.response.id, "executor-a", renewed_expiry)
    stale.response = stale.response.model_copy(update={"status": AgentRunStatus.STREAMING})
    await repository.transition_run(
        stale,
        "agent.run.started",
        {"status": "streaming"},
        frozenset({AgentRunStatus.QUEUED}),
        "executor-a",
    )
    latest = await repository.get_run("owner-a", run.response.id)
    assert latest.execution_lease_expires_at == renewed_expiry

    repository.runs[run.response.id].execution_lease_expires_at = datetime.now(UTC) - timedelta(
        seconds=1
    )
    with pytest.raises(AgentExecutionOwned):
        await repository.renew_run_execution(
            "owner-a",
            run.response.id,
            "executor-a",
            datetime.now(UTC) + timedelta(seconds=30),
        )


def test_active_run_unique_index_remains_partial_on_sqlite() -> None:
    index = next(
        item
        for item in AgentRunModel.__table__.indexes
        if item.name == "uq_agent_runs_owner_active"
    )
    ddl = str(CreateIndex(index).compile(dialect=sqlite.dialect()))
    assert "CREATE UNIQUE INDEX" in ddl
    assert "WHERE status IN" in ddl
    assert "'cancelling'" in ddl


@pytest.mark.asyncio
async def test_agent_repository_owner_isolation_idempotency_and_events() -> None:
    repository = InMemoryAgentRepository()
    thread = await repository.get_or_create_thread("owner-a", "conversation-1", "prompt-v1")
    repeated_thread = await repository.get_or_create_thread(
        "owner-a", "conversation-1", "prompt-v1"
    )
    assert repeated_thread.id == thread.id
    with pytest.raises(KeyError):
        await repository.get_thread("owner-b", thread.id)

    first, created = await repository.create_run(
        stored_run(
            "owner-a",
            thread.id,
            run_id="agent-run-1",
            key="request-1",
            request_hash="a" * 64,
        ),
        AgentMessageContent(text="Improve this"),
    )
    assert created is True
    repeated, created = await repository.create_run(
        stored_run(
            "owner-a",
            thread.id,
            run_id="agent-run-different",
            key="request-1",
            request_hash="a" * 64,
        ),
        AgentMessageContent(text="Improve this"),
    )
    assert created is False
    assert repeated.response.id == first.response.id

    with pytest.raises(ValueError, match="IDEMPOTENCY_KEY_REUSED"):
        await repository.create_run(
            stored_run(
                "owner-a",
                thread.id,
                run_id="agent-run-conflict",
                key="request-1",
                request_hash="b" * 64,
            ),
            AgentMessageContent(text="Different"),
        )
    with pytest.raises(KeyError):
        await repository.get_run("owner-b", first.response.id)

    first.response = first.response.model_copy(
        update={"status": AgentRunStatus.STREAMING, "started_at": datetime.now(UTC)}
    )
    started = await repository.transition_run(
        first,
        "agent.run.started",
        {"status": "streaming"},
        frozenset({AgentRunStatus.QUEUED}),
    )
    first.response = first.response.model_copy(
        update={"status": AgentRunStatus.COMPLETED, "finished_at": datetime.now(UTC)}
    )
    message = await repository.finish_run(
        first,
        AgentMessageContent(
            text="Improved",
            draftProposal={"prompt": "An improved lake prompt"},
        ),
        "agent.run.completed",
        {"status": "completed"},
        frozenset({AgentRunStatus.STREAMING}),
    )
    messages = await repository.list_messages("owner-a", thread.id)
    events = await repository.list_events("owner-a", first.response.id, started.id - 1)
    assert [item.role.value for item in messages] == ["user", "assistant"]
    assert message.content.draft_proposal is not None
    assert [event.event_type for event in events] == [
        "agent.run.started",
        "agent.run.completed",
    ]
    assert events[0].id < events[1].id


@pytest.mark.asyncio
async def test_agent_repository_compare_and_swap_rejects_stale_transition() -> None:
    repository = InMemoryAgentRepository()
    thread = await repository.get_or_create_thread("owner-a", "conversation-1", "prompt-v1")
    run, _ = await repository.create_run(
        stored_run(
            "owner-a",
            thread.id,
            run_id="agent-run-cas",
            key="request-cas",
            request_hash="c" * 64,
        ),
        AgentMessageContent(text="CAS"),
    )
    run.response = run.response.model_copy(update={"status": AgentRunStatus.STREAMING})
    await repository.transition_run(
        run,
        "agent.run.started",
        {"status": "streaming"},
        frozenset({AgentRunStatus.QUEUED}),
    )
    stale = await repository.get_run("owner-a", run.response.id)
    cancelling = await repository.get_run("owner-a", run.response.id)
    cancelling.response = cancelling.response.model_copy(
        update={"status": AgentRunStatus.CANCELLING}
    )
    await repository.transition_run(
        cancelling,
        "agent.run.cancelling",
        {"status": "cancelling"},
        frozenset({AgentRunStatus.STREAMING}),
    )
    stale.response = stale.response.model_copy(update={"status": AgentRunStatus.FAILED})
    with pytest.raises(AgentStateConflict) as exc_info:
        await repository.transition_run(
            stale,
            "agent.run.failed",
            {"status": "failed"},
            frozenset({AgentRunStatus.STREAMING}),
        )
    assert exc_info.value.latest.response.status is AgentRunStatus.CANCELLING


@pytest.mark.asyncio
async def test_agent_repository_event_reads_are_bounded() -> None:
    repository = InMemoryAgentRepository()
    thread = await repository.get_or_create_thread("owner-a", "conversation-1", "prompt-v1")
    run, _ = await repository.create_run(
        stored_run(
            "owner-a",
            thread.id,
            run_id="agent-run-events",
            key="request-events",
            request_hash="d" * 64,
        ),
        AgentMessageContent(text="Events"),
    )
    for index in range(5):
        await repository.append_event("owner-a", run.response.id, "agent.test", {"index": index})
    events = await repository.list_events("owner-a", run.response.id, limit=2)
    assert len(events) == 2
    assert events[0].id < events[1].id


@pytest.mark.asyncio
async def test_agent_repository_enforces_one_active_run_per_owner() -> None:
    repository = InMemoryAgentRepository()
    first_thread = await repository.get_or_create_thread("owner-a", "conversation-1", "prompt-v1")
    await repository.create_run(
        stored_run(
            "owner-a",
            first_thread.id,
            run_id="agent-run-1",
            key="request-1",
            request_hash="a" * 64,
        ),
        AgentMessageContent(text="First"),
    )
    second_thread = await repository.get_or_create_thread("owner-a", "conversation-2", "prompt-v1")
    with pytest.raises(RuntimeError, match="AGENT_RUN_CONCURRENCY_LIMIT"):
        await repository.create_run(
            stored_run(
                "owner-a",
                second_thread.id,
                run_id="agent-run-2",
                key="request-2",
                request_hash="b" * 64,
            ),
            AgentMessageContent(text="Second"),
        )
