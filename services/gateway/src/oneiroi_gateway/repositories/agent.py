import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import uuid4

from oneiroi_common.agent import (
    AgentEventResponse,
    AgentMessageContent,
    AgentMessageResponse,
    AgentMessageRole,
    AgentMessageStatus,
    AgentRunResponse,
    AgentRunStatus,
    AgentThreadResponse,
    AgentThreadStatus,
)


def utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(slots=True)
class StoredAgentThread:
    owner_id: str
    response: AgentThreadResponse


@dataclass(slots=True)
class StoredAgentRun:
    owner_id: str
    response: AgentRunResponse
    idempotency_key: str
    request_hash: str


class AgentStateConflict(RuntimeError):
    def __init__(self, latest: StoredAgentRun) -> None:
        self.latest = latest
        super().__init__("AGENT_STATE_CONFLICT")


class AgentRepository(Protocol):
    async def get_or_create_thread(
        self, owner_id: str, conversation_id: str, prompt_version: str
    ) -> AgentThreadResponse: ...

    async def get_thread(self, owner_id: str, thread_id: str) -> AgentThreadResponse: ...

    async def get_thread_by_conversation(
        self, owner_id: str, conversation_id: str
    ) -> AgentThreadResponse: ...

    async def list_messages(
        self, owner_id: str, thread_id: str, after_sequence: int = 0, limit: int = 50
    ) -> list[AgentMessageResponse]: ...

    async def create_run(
        self,
        run: StoredAgentRun,
        user_content: AgentMessageContent,
    ) -> tuple[StoredAgentRun, bool]: ...

    async def get_run(self, owner_id: str, run_id: str) -> StoredAgentRun: ...

    async def list_incomplete_runs(self) -> list[StoredAgentRun]: ...

    async def transition_run(
        self,
        run: StoredAgentRun,
        event_type: str,
        payload: dict[str, object],
        expected_statuses: frozenset[AgentRunStatus],
    ) -> AgentEventResponse: ...

    async def append_event(
        self,
        owner_id: str,
        run_id: str,
        event_type: str,
        payload: dict[str, object],
        expected_statuses: frozenset[AgentRunStatus] | None = None,
    ) -> AgentEventResponse: ...

    async def finish_run(
        self,
        run: StoredAgentRun,
        assistant_content: AgentMessageContent,
        event_type: str,
        payload: dict[str, object],
        expected_statuses: frozenset[AgentRunStatus],
    ) -> AgentMessageResponse: ...

    async def list_events(
        self, owner_id: str, run_id: str, after_id: int = 0, limit: int = 200
    ) -> list[AgentEventResponse]: ...


class InMemoryAgentRepository:
    def __init__(self) -> None:
        self.threads: dict[str, StoredAgentThread] = {}
        self.thread_by_conversation: dict[str, str] = {}
        self.messages: dict[str, list[tuple[str, AgentMessageResponse]]] = {}
        self.runs: dict[str, StoredAgentRun] = {}
        self.idempotency: dict[tuple[str, str], str] = {}
        self.events: dict[str, list[tuple[str, AgentEventResponse]]] = {}
        self._event_id = 1
        self._lock = asyncio.Lock()

    async def get_or_create_thread(
        self, owner_id: str, conversation_id: str, prompt_version: str
    ) -> AgentThreadResponse:
        async with self._lock:
            if thread_id := self.thread_by_conversation.get(conversation_id):
                stored = self.threads[thread_id]
                if stored.owner_id != owner_id:
                    raise KeyError(conversation_id)
                return stored.response.model_copy(deep=True)
            now = utc_now()
            response = AgentThreadResponse(
                id=f"agent-thread-{uuid4().hex[:20]}",
                conversationId=conversation_id,
                status=AgentThreadStatus.ACTIVE,
                promptVersion=prompt_version,
                createdAt=now,
                updatedAt=now,
            )
            self.threads[response.id] = StoredAgentThread(owner_id, response)
            self.thread_by_conversation[conversation_id] = response.id
            return response.model_copy(deep=True)

    async def get_thread(self, owner_id: str, thread_id: str) -> AgentThreadResponse:
        stored = self.threads.get(thread_id)
        if stored is None or stored.owner_id != owner_id:
            raise KeyError(thread_id)
        return stored.response.model_copy(deep=True)

    async def get_thread_by_conversation(
        self, owner_id: str, conversation_id: str
    ) -> AgentThreadResponse:
        thread_id = self.thread_by_conversation.get(conversation_id)
        if thread_id is None:
            raise KeyError(conversation_id)
        return await self.get_thread(owner_id, thread_id)

    async def list_messages(
        self,
        owner_id: str,
        thread_id: str,
        after_sequence: int = 0,
        limit: int = 50,
    ) -> list[AgentMessageResponse]:
        await self.get_thread(owner_id, thread_id)
        return [
            message.model_copy(deep=True)
            for message_owner, message in self.messages.get(thread_id, [])
            if message_owner == owner_id and message.sequence > after_sequence
        ][:limit]

    async def create_run(
        self,
        run: StoredAgentRun,
        user_content: AgentMessageContent,
    ) -> tuple[StoredAgentRun, bool]:
        async with self._lock:
            idempotency_key = (run.owner_id, run.idempotency_key)
            if run_id := self.idempotency.get(idempotency_key):
                existing = self.runs[run_id]
                if existing.request_hash != run.request_hash:
                    raise ValueError("IDEMPOTENCY_KEY_REUSED")
                return _copy_run(existing), False
            for existing in self.runs.values():
                if existing.owner_id == run.owner_id and not existing.response.status.is_terminal:
                    raise RuntimeError("AGENT_RUN_CONCURRENCY_LIMIT")
            thread = self.threads.get(run.response.thread_id)
            if thread is None or thread.owner_id != run.owner_id:
                raise KeyError(run.response.thread_id)
            self.runs[run.response.id] = _copy_run(run)
            self.idempotency[idempotency_key] = run.response.id
            sequence = len(self.messages.get(run.response.thread_id, [])) + 1
            now = utc_now()
            message = AgentMessageResponse(
                id=f"agent-message-{uuid4().hex[:20]}",
                threadId=run.response.thread_id,
                runId=run.response.id,
                sequence=sequence,
                role=AgentMessageRole.USER,
                content=user_content,
                status=AgentMessageStatus.COMPLETED,
                createdAt=now,
                completedAt=now,
            )
            self.messages.setdefault(run.response.thread_id, []).append((run.owner_id, message))
            self._append_event_locked(
                run.owner_id,
                run.response,
                "agent.run.queued",
                {"status": run.response.status.value},
            )
            thread.response = thread.response.model_copy(update={"updated_at": now})
            return _copy_run(run), True

    async def get_run(self, owner_id: str, run_id: str) -> StoredAgentRun:
        run = self.runs.get(run_id)
        if run is None or run.owner_id != owner_id:
            raise KeyError(run_id)
        return _copy_run(run)

    async def list_incomplete_runs(self) -> list[StoredAgentRun]:
        return [_copy_run(run) for run in self.runs.values() if not run.response.status.is_terminal]

    async def transition_run(
        self,
        run: StoredAgentRun,
        event_type: str,
        payload: dict[str, object],
        expected_statuses: frozenset[AgentRunStatus],
    ) -> AgentEventResponse:
        async with self._lock:
            existing = self.runs.get(run.response.id)
            if existing is None or existing.owner_id != run.owner_id:
                raise KeyError(run.response.id)
            if existing.response.status not in expected_statuses:
                raise AgentStateConflict(_copy_run(existing))
            self.runs[run.response.id] = _copy_run(run)
            return self._append_event_locked(run.owner_id, run.response, event_type, payload)

    async def append_event(
        self,
        owner_id: str,
        run_id: str,
        event_type: str,
        payload: dict[str, object],
        expected_statuses: frozenset[AgentRunStatus] | None = None,
    ) -> AgentEventResponse:
        async with self._lock:
            run = self.runs.get(run_id)
            if run is None or run.owner_id != owner_id:
                raise KeyError(run_id)
            if expected_statuses is not None and run.response.status not in expected_statuses:
                raise AgentStateConflict(_copy_run(run))
            return self._append_event_locked(owner_id, run.response, event_type, payload)

    async def finish_run(
        self,
        run: StoredAgentRun,
        assistant_content: AgentMessageContent,
        event_type: str,
        payload: dict[str, object],
        expected_statuses: frozenset[AgentRunStatus],
    ) -> AgentMessageResponse:
        async with self._lock:
            existing = self.runs.get(run.response.id)
            if existing is None or existing.owner_id != run.owner_id:
                raise KeyError(run.response.id)
            if existing.response.status not in expected_statuses:
                raise AgentStateConflict(_copy_run(existing))
            sequence = len(self.messages.get(run.response.thread_id, [])) + 1
            now = utc_now()
            message = AgentMessageResponse(
                id=f"agent-message-{uuid4().hex[:20]}",
                threadId=run.response.thread_id,
                runId=run.response.id,
                sequence=sequence,
                role=AgentMessageRole.ASSISTANT,
                content=assistant_content,
                status=AgentMessageStatus.COMPLETED,
                createdAt=now,
                completedAt=now,
            )
            run.response = run.response.model_copy(update={"output_message_id": message.id})
            self.runs[run.response.id] = _copy_run(run)
            self.messages.setdefault(run.response.thread_id, []).append((run.owner_id, message))
            self._append_event_locked(run.owner_id, run.response, event_type, payload)
            return message.model_copy(deep=True)

    async def list_events(
        self, owner_id: str, run_id: str, after_id: int = 0, limit: int = 200
    ) -> list[AgentEventResponse]:
        await self.get_run(owner_id, run_id)
        return [
            event.model_copy(deep=True)
            for event_owner, event in self.events.get(run_id, [])
            if event_owner == owner_id and event.id > after_id
        ][:limit]

    def _append_event_locked(
        self,
        owner_id: str,
        run: AgentRunResponse,
        event_type: str,
        payload: dict[str, object],
    ) -> AgentEventResponse:
        items = self.events.setdefault(run.id, [])
        event = AgentEventResponse(
            id=self._event_id,
            runId=run.id,
            threadId=run.thread_id,
            eventType=event_type,
            sequence=len(items) + 1,
            payload=payload,
            createdAt=utc_now(),
        )
        self._event_id += 1
        items.append((owner_id, event))
        return event.model_copy(deep=True)


def _copy_run(run: StoredAgentRun) -> StoredAgentRun:
    return StoredAgentRun(
        owner_id=run.owner_id,
        response=run.response.model_copy(deep=True),
        idempotency_key=run.idempotency_key,
        request_hash=run.request_hash,
    )
