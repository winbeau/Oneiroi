import asyncio
import json
from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient

from oneiroi_common.agent import (
    AgentEventResponse,
    AgentMessageContent,
    AgentMessageResponse,
    AgentRunCreate,
    AgentRunResponse,
    AgentRunStatus,
)
from oneiroi_gateway.agent.fake import FakeAgentProvider
from oneiroi_gateway.agent.protocol import ProviderEvent, ProviderEventType
from oneiroi_gateway.agent.runtime import AgentRuntime
from oneiroi_gateway.main import create_app
from oneiroi_gateway.repositories.agent import InMemoryAgentRepository, StoredAgentRun
from oneiroi_gateway.repositories.studio import InMemoryStudioRepository
from oneiroi_gateway.settings import GatewaySettings


class CancellingRaceRepository(InMemoryAgentRepository):
    def __init__(self, race_on: str) -> None:
        super().__init__()
        self.race_on = race_on
        self.triggered = False

    async def _begin_cancel(self, owner_id: str, run_id: str) -> None:
        current = await self.get_run(owner_id, run_id)
        if current.response.status is not AgentRunStatus.STREAMING:
            return
        current.response = current.response.model_copy(update={"status": AgentRunStatus.CANCELLING})
        await super().transition_run(
            current,
            "agent.run.cancelling",
            {"status": "cancelling"},
            frozenset({AgentRunStatus.STREAMING}),
        )

    async def append_event(
        self,
        owner_id: str,
        run_id: str,
        event_type: str,
        payload: dict[str, object],
        expected_statuses: frozenset[AgentRunStatus] | None = None,
    ) -> AgentEventResponse:
        if not self.triggered and self.race_on == "append" and event_type == "agent.message.delta":
            self.triggered = True
            await self._begin_cancel(owner_id, run_id)
        return await super().append_event(owner_id, run_id, event_type, payload, expected_statuses)

    async def finish_run(
        self,
        run: StoredAgentRun,
        assistant_content: AgentMessageContent,
        event_type: str,
        payload: dict[str, object],
        expected_statuses: frozenset[AgentRunStatus],
    ) -> AgentMessageResponse:
        if not self.triggered and self.race_on == "finish":
            self.triggered = True
            await self._begin_cancel(run.owner_id, run.response.id)
        return await super().finish_run(
            run,
            assistant_content,
            event_type,
            payload,
            expected_statuses,
        )


def response_events(payload: dict[str, object]) -> list[ProviderEvent]:
    text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    midpoint = len(text) // 2
    return [
        ProviderEvent(event_type=ProviderEventType.RESPONSE_STARTED, response_id="response-1"),
        ProviderEvent(
            event_type=ProviderEventType.TEXT_DELTA,
            response_id="response-1",
            data={"delta": text[:midpoint]},
        ),
        ProviderEvent(
            event_type=ProviderEventType.TEXT_DELTA,
            response_id="response-1",
            data={"delta": text[midpoint:]},
        ),
        ProviderEvent(
            event_type=ProviderEventType.USAGE_COMPLETED,
            response_id="response-1",
            data={"inputTokens": 12, "outputTokens": 8, "totalTokens": 20},
        ),
        ProviderEvent(event_type=ProviderEventType.RESPONSE_COMPLETED, response_id="response-1"),
    ]


async def wait_for_terminal(client: AsyncClient, run_id: str, owner: str = "owner-a") -> dict:
    for _ in range(100):
        response = await client.get(f"/v1/agent/runs/{run_id}", headers={"X-Oneiroi-User": owner})
        if response.json()["status"] in {"completed", "failed", "cancelled", "expired"}:
            return response.json()
        await asyncio.sleep(0.01)
    raise AssertionError("Agent run did not reach a terminal state")


@pytest.mark.asyncio
async def test_agent_run_persists_thread_messages_proposal_and_replay() -> None:
    provider = FakeAgentProvider(
        events=response_events(
            {
                "text": "已整理为更稳定的镜头描述。",
                "draftProposal": {
                    "prompt": "清晨湖面，镜头缓慢前推，薄雾保持连续",
                    "duration": 5,
                },
                "rationale": ["补充了镜头运动与连续性"],
                "warnings": [],
            }
        )
    )
    app = create_app(GatewaySettings(_env_file=None), agent_provider=provider)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        headers = {"X-Oneiroi-User": "owner-a"}
        conversation = await client.post(
            "/v1/conversations", headers=headers, json={"title": "Agent test"}
        )
        conversation_id = conversation.json()["id"]
        before_thread = await client.get(
            f"/v1/conversations/{conversation_id}/agent/thread", headers=headers
        )
        assert before_thread.status_code == 404

        request = {
            "conversationId": conversation_id,
            "message": "请增强这个提示词",
            "draftSnapshot": {"prompt": "湖面"},
            "assetIds": [],
            "mode": "assist",
        }
        missing_key = await client.post("/v1/agent/runs", headers=headers, json=request)
        assert missing_key.status_code == 400
        created = await client.post(
            "/v1/agent/runs",
            headers={**headers, "Idempotency-Key": "agent-request-1"},
            json=request,
        )
        assert created.status_code == 202
        run_id = created.json()["id"]
        repeated = await client.post(
            "/v1/agent/runs",
            headers={**headers, "Idempotency-Key": "agent-request-1"},
            json=request,
        )
        assert repeated.json()["id"] == run_id
        conflict = await client.post(
            "/v1/agent/runs",
            headers={**headers, "Idempotency-Key": "agent-request-1"},
            json=request | {"message": "different"},
        )
        assert conflict.status_code == 409
        terminal = await wait_for_terminal(client, run_id)
        assert terminal["status"] == "completed"
        assert terminal["inputSnapshot"]["draftSnapshot"]["prompt"] == "湖面"
        assert terminal["usage"] == {
            "inputTokens": 12,
            "outputTokens": 8,
            "totalTokens": 20,
            "providerRequests": 1,
        }

        thread = await client.get(
            f"/v1/conversations/{conversation_id}/agent/thread", headers=headers
        )
        messages = await client.get(
            f"/v1/agent/threads/{thread.json()['id']}/messages", headers=headers
        )
        assert [message["role"] for message in messages.json()] == ["user", "assistant"]
        proposal = messages.json()[1]["content"]["draftProposal"]
        assert proposal["prompt"].startswith("清晨湖面")
        assert request["draftSnapshot"]["prompt"] == "湖面"

        stream = await client.get(f"/v1/agent/runs/{run_id}/events", headers=headers)
        assert stream.status_code == 200
        event_ids = [
            int(line.removeprefix("id: "))
            for line in stream.text.splitlines()
            if line.startswith("id: ")
        ]
        assert event_ids == sorted(set(event_ids))
        assert "event: agent.draft.proposed" in stream.text
        assert "event: agent.run.completed" in stream.text
        replay = await client.get(
            f"/v1/agent/runs/{run_id}/events",
            headers={**headers, "Last-Event-ID": str(event_ids[-2])},
        )
        assert f"id: {event_ids[-1]}" in replay.text
        assert f"id: {event_ids[0]}" not in replay.text

        hidden_run = await client.get(
            f"/v1/agent/runs/{run_id}", headers={"X-Oneiroi-User": "owner-b"}
        )
        hidden_messages = await client.get(
            f"/v1/agent/threads/{thread.json()['id']}/messages",
            headers={"X-Oneiroi-User": "owner-b"},
        )
        hidden_events = await client.get(
            f"/v1/agent/runs/{run_id}/events",
            headers={"X-Oneiroi-User": "owner-b"},
        )
        assert (
            hidden_run.status_code
            == hidden_messages.status_code
            == hidden_events.status_code
            == 404
        )
        invalid_cursor = await client.get(
            f"/v1/agent/runs/{run_id}/events",
            headers={**headers, "Last-Event-ID": "invalid"},
        )
        assert invalid_cursor.status_code == 400
    await app.state.agent_runtime.close()


@pytest.mark.asyncio
async def test_agent_cancel_and_invalid_output_have_explicit_terminal_states() -> None:
    slow_provider = FakeAgentProvider(events=response_events({"text": "late"}), delay_seconds=1)
    app = create_app(GatewaySettings(_env_file=None), agent_provider=slow_provider)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        headers = {"X-Oneiroi-User": "owner-a"}
        conversation = await client.post(
            "/v1/conversations", headers=headers, json={"title": "Cancel"}
        )
        created = await client.post(
            "/v1/agent/runs",
            headers={**headers, "Idempotency-Key": "cancel-1"},
            json={
                "conversationId": conversation.json()["id"],
                "message": "cancel me",
                "draftSnapshot": {"prompt": "lake"},
            },
        )
        cancelled = await client.post(
            f"/v1/agent/runs/{created.json()['id']}/cancel", headers=headers
        )
        assert cancelled.json()["status"] == "cancelled"
    await app.state.agent_runtime.close()

    invalid_provider = FakeAgentProvider(
        events=[
            ProviderEvent(
                event_type=ProviderEventType.TEXT_DELTA,
                data={"delta": "not-json"},
            ),
            ProviderEvent(event_type=ProviderEventType.RESPONSE_COMPLETED),
        ]
    )
    app = create_app(GatewaySettings(_env_file=None), agent_provider=invalid_provider)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        headers = {"X-Oneiroi-User": "owner-a"}
        conversation = await client.post(
            "/v1/conversations", headers=headers, json={"title": "Invalid"}
        )
        created = await client.post(
            "/v1/agent/runs",
            headers={**headers, "Idempotency-Key": "invalid-1"},
            json={
                "conversationId": conversation.json()["id"],
                "message": "invalid output",
                "draftSnapshot": {"prompt": "lake"},
            },
        )
        terminal = await wait_for_terminal(client, created.json()["id"])
        assert terminal["status"] == "failed"
        assert terminal["errorCode"] == "AGENT_OUTPUT_INVALID"
        assert "not-json" not in terminal["errorMessage"]
    await app.state.agent_runtime.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("race_on", ["append", "finish"])
async def test_agent_cancel_race_finishes_cancelled_without_failure(race_on: str) -> None:
    studio = InMemoryStudioRepository()
    conversation = await studio.create_conversation("owner-a", "Cancel race")
    repository = CancellingRaceRepository(race_on)
    runtime = AgentRuntime(
        repository,
        studio,
        FakeAgentProvider(events=response_events({"text": "safe"})),
        GatewaySettings(_env_file=None),
    )
    created = await runtime.create_run(
        "owner-a",
        AgentRunCreate(
            conversationId=conversation.id,
            message="race",
            draftSnapshot={"prompt": "lake"},
        ),
        f"cancel-race-{race_on}",
    )
    for _ in range(100):
        snapshot = await runtime.get_run("owner-a", created.id)
        if snapshot.status.is_terminal:
            break
        await asyncio.sleep(0.01)
    events = await repository.list_events("owner-a", created.id)
    assert snapshot.status is AgentRunStatus.CANCELLED
    assert "agent.run.cancelled" in [event.event_type for event in events]
    assert "agent.run.failed" not in [event.event_type for event in events]
    await runtime.close()


@pytest.mark.asyncio
async def test_agent_run_fails_closed_when_provider_event_limit_is_exceeded() -> None:
    provider = FakeAgentProvider(
        events=[
            ProviderEvent(
                event_type=ProviderEventType.TEXT_DELTA,
                data={"delta": "x"},
            )
            for _ in range(11)
        ]
    )
    app = create_app(
        GatewaySettings(_env_file=None, agent_max_events_per_run=10),
        agent_provider=provider,
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        headers = {"X-Oneiroi-User": "owner-a"}
        conversation = await client.post(
            "/v1/conversations", headers=headers, json={"title": "Event limit"}
        )
        created = await client.post(
            "/v1/agent/runs",
            headers={**headers, "Idempotency-Key": "event-limit-1"},
            json={
                "conversationId": conversation.json()["id"],
                "message": "too many events",
                "draftSnapshot": {"prompt": "lake"},
            },
        )
        terminal = await wait_for_terminal(client, created.json()["id"])
    assert terminal["status"] == "failed"
    assert terminal["errorCode"] == "AGENT_OUTPUT_INVALID"
    await app.state.agent_runtime.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "interrupted_status",
    [AgentRunStatus.STREAMING, AgentRunStatus.WAITING_APPROVAL],
)
async def test_restart_recovery_deterministically_terminates_incomplete_run(
    interrupted_status: AgentRunStatus,
) -> None:
    studio = InMemoryStudioRepository()
    conversation = await studio.create_conversation("owner-a", "Recovery")
    repository = InMemoryAgentRepository()
    thread = await repository.get_or_create_thread("owner-a", conversation.id, "oneiroi-agent-v1")
    now = datetime.now(UTC)
    stored = StoredAgentRun(
        owner_id="owner-a",
        idempotency_key="recovery-1",
        request_hash="a" * 64,
        response=AgentRunResponse(
            id="agent-run-recovery",
            threadId=thread.id,
            conversationId=conversation.id,
            status=AgentRunStatus.QUEUED,
            model="fake-model",
            provider="fake",
            transport="sse",
            reasoningEffort="high",
            promptVersion="oneiroi-agent-v1",
            toolsetVersion="oneiroi-tools-v1",
            inputSnapshot={"draftSnapshot": {"prompt": "lake"}},
            createdAt=now,
        ),
    )
    stored, _ = await repository.create_run(stored, AgentMessageContent(text="recover"))
    stored.response = stored.response.model_copy(
        update={"status": AgentRunStatus.STREAMING, "started_at": now}
    )
    await repository.transition_run(
        stored,
        "agent.run.started",
        {"status": "streaming"},
        frozenset({AgentRunStatus.QUEUED}),
    )
    if interrupted_status is AgentRunStatus.WAITING_APPROVAL:
        stored.response = stored.response.model_copy(
            update={"status": AgentRunStatus.WAITING_APPROVAL}
        )
        await repository.transition_run(
            stored,
            "agent.run.waiting_approval",
            {"status": "waiting_approval"},
            frozenset({AgentRunStatus.STREAMING}),
        )
    runtime = AgentRuntime(repository, studio, None, GatewaySettings(_env_file=None))
    recovered = await runtime.recover_incomplete()
    snapshot = await runtime.get_run("owner-a", stored.response.id)
    assert recovered == [stored.response.id]
    assert snapshot.status == "failed"
    assert snapshot.error_code == "AGENT_RECOVERY_REQUIRED"
