import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import uuid4

from oneiroi_common.agent import (
    AgentApprovalResponse,
    AgentApprovalStatus,
    AgentEventResponse,
    AgentMessageContent,
    AgentMessageResponse,
    AgentMessageRole,
    AgentMessageStatus,
    AgentRunResponse,
    AgentRunStatus,
    AgentThreadResponse,
    AgentThreadStatus,
    AgentToolCallResponse,
    AgentToolCallStatus,
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
    executor_id: str | None = None
    execution_lease_expires_at: datetime | None = None


@dataclass(slots=True)
class StoredAgentToolCall:
    owner_id: str
    provider_call_id: str
    response: AgentToolCallResponse


@dataclass(slots=True)
class StoredAgentApproval:
    owner_id: str
    response: AgentApprovalResponse
    decision_metadata: dict[str, object]


@dataclass(slots=True)
class AgentToolDecision:
    tool_call: StoredAgentToolCall
    approval: StoredAgentApproval
    run: StoredAgentRun
    claimed: bool
    approved: bool


class AgentExecutionOwned(RuntimeError):
    def __init__(self, latest: StoredAgentRun) -> None:
        self.latest = latest
        super().__init__("AGENT_EXECUTION_OWNED")


class AgentStateConflict(RuntimeError):
    def __init__(self, latest: StoredAgentRun) -> None:
        self.latest = latest
        super().__init__("AGENT_STATE_CONFLICT")


def _assert_execution_owned(run: StoredAgentRun, executor_id: str | None) -> None:
    if executor_id is None:
        return
    if (
        run.executor_id != executor_id
        or run.execution_lease_expires_at is None
        or run.execution_lease_expires_at <= utc_now()
    ):
        raise AgentExecutionOwned(_copy_run(run))


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

    async def list_recoverable_runs(self, now: datetime) -> list[StoredAgentRun]: ...

    async def claim_run_execution(
        self,
        owner_id: str,
        run_id: str,
        executor_id: str,
        lease_expires_at: datetime,
    ) -> StoredAgentRun: ...

    async def renew_run_execution(
        self,
        owner_id: str,
        run_id: str,
        executor_id: str,
        lease_expires_at: datetime,
    ) -> StoredAgentRun: ...

    async def release_run_execution(
        self, owner_id: str, run_id: str, executor_id: str
    ) -> StoredAgentRun: ...

    async def transition_run(
        self,
        run: StoredAgentRun,
        event_type: str,
        payload: dict[str, object],
        expected_statuses: frozenset[AgentRunStatus],
        executor_id: str | None = None,
    ) -> AgentEventResponse: ...

    async def append_event(
        self,
        owner_id: str,
        run_id: str,
        event_type: str,
        payload: dict[str, object],
        expected_statuses: frozenset[AgentRunStatus] | None = None,
        executor_id: str | None = None,
    ) -> AgentEventResponse: ...

    async def finish_run(
        self,
        run: StoredAgentRun,
        assistant_content: AgentMessageContent,
        event_type: str,
        payload: dict[str, object],
        expected_statuses: frozenset[AgentRunStatus],
        executor_id: str | None = None,
    ) -> AgentMessageResponse: ...

    async def propose_tool_call(
        self,
        run: StoredAgentRun,
        tool_call: StoredAgentToolCall,
        approval: StoredAgentApproval | None,
        executor_id: str | None = None,
    ) -> tuple[StoredAgentToolCall, StoredAgentApproval | None, bool]: ...

    async def get_tool_call(self, owner_id: str, tool_call_id: str) -> StoredAgentToolCall: ...

    async def list_tool_calls(self, owner_id: str, run_id: str) -> list[StoredAgentToolCall]: ...

    async def start_tool(
        self,
        owner_id: str,
        tool_call_id: str,
        expected_run_statuses: frozenset[AgentRunStatus],
        expected_tool_statuses: frozenset[AgentToolCallStatus],
        executor_id: str | None = None,
    ) -> StoredAgentToolCall: ...

    async def finish_tool(
        self,
        owner_id: str,
        tool_call_id: str,
        *,
        status: AgentToolCallStatus,
        result: dict[str, object] | None,
        error_code: str | None = None,
        error_message: str | None = None,
        executor_id: str | None = None,
    ) -> StoredAgentToolCall: ...

    async def get_approval_by_tool_call(
        self, owner_id: str, tool_call_id: str
    ) -> StoredAgentApproval: ...

    async def list_pending_approvals(self) -> list[StoredAgentApproval]: ...

    async def decide_approval(
        self,
        owner_id: str,
        tool_call_id: str,
        *,
        approve: bool,
        decision_metadata: dict[str, object],
        executor_id: str,
        lease_expires_at: datetime,
    ) -> AgentToolDecision: ...

    async def expire_approval(self, owner_id: str, tool_call_id: str) -> AgentToolDecision: ...

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
        self.tool_calls: dict[str, StoredAgentToolCall] = {}
        self.tool_call_by_provider: dict[tuple[str, str], str] = {}
        self.approvals: dict[str, StoredAgentApproval] = {}
        self.approval_by_tool_call: dict[str, str] = {}
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

    async def list_recoverable_runs(self, now: datetime) -> list[StoredAgentRun]:
        return [
            _copy_run(run)
            for run in self.runs.values()
            if not run.response.status.is_terminal
            and (
                run.executor_id is None
                or run.execution_lease_expires_at is None
                or run.execution_lease_expires_at <= now
            )
        ]

    async def claim_run_execution(
        self,
        owner_id: str,
        run_id: str,
        executor_id: str,
        lease_expires_at: datetime,
    ) -> StoredAgentRun:
        async with self._lock:
            run = self.runs.get(run_id)
            if run is None or run.owner_id != owner_id:
                raise KeyError(run_id)
            if (
                run.executor_id not in {None, executor_id}
                and run.execution_lease_expires_at is not None
                and run.execution_lease_expires_at > utc_now()
            ):
                raise AgentExecutionOwned(_copy_run(run))
            run.executor_id = executor_id
            run.execution_lease_expires_at = lease_expires_at
            return _copy_run(run)

    async def renew_run_execution(
        self,
        owner_id: str,
        run_id: str,
        executor_id: str,
        lease_expires_at: datetime,
    ) -> StoredAgentRun:
        async with self._lock:
            run = self.runs.get(run_id)
            if run is None or run.owner_id != owner_id:
                raise KeyError(run_id)
            if (
                run.executor_id != executor_id
                or run.execution_lease_expires_at is None
                or run.execution_lease_expires_at <= utc_now()
            ):
                raise AgentExecutionOwned(_copy_run(run))
            run.execution_lease_expires_at = lease_expires_at
            return _copy_run(run)

    async def release_run_execution(
        self, owner_id: str, run_id: str, executor_id: str
    ) -> StoredAgentRun:
        async with self._lock:
            run = self.runs.get(run_id)
            if run is None or run.owner_id != owner_id:
                raise KeyError(run_id)
            if run.executor_id == executor_id:
                run.executor_id = None
                run.execution_lease_expires_at = None
            return _copy_run(run)

    async def transition_run(
        self,
        run: StoredAgentRun,
        event_type: str,
        payload: dict[str, object],
        expected_statuses: frozenset[AgentRunStatus],
        executor_id: str | None = None,
    ) -> AgentEventResponse:
        async with self._lock:
            existing = self.runs.get(run.response.id)
            if existing is None or existing.owner_id != run.owner_id:
                raise KeyError(run.response.id)
            _assert_execution_owned(existing, executor_id)
            if existing.response.status not in expected_statuses:
                raise AgentStateConflict(_copy_run(existing))
            updated = _copy_run(run)
            updated.executor_id = existing.executor_id
            updated.execution_lease_expires_at = existing.execution_lease_expires_at
            self.runs[run.response.id] = updated
            return self._append_event_locked(run.owner_id, run.response, event_type, payload)

    async def append_event(
        self,
        owner_id: str,
        run_id: str,
        event_type: str,
        payload: dict[str, object],
        expected_statuses: frozenset[AgentRunStatus] | None = None,
        executor_id: str | None = None,
    ) -> AgentEventResponse:
        async with self._lock:
            run = self.runs.get(run_id)
            if run is None or run.owner_id != owner_id:
                raise KeyError(run_id)
            _assert_execution_owned(run, executor_id)
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
        executor_id: str | None = None,
    ) -> AgentMessageResponse:
        async with self._lock:
            existing = self.runs.get(run.response.id)
            if existing is None or existing.owner_id != run.owner_id:
                raise KeyError(run.response.id)
            _assert_execution_owned(existing, executor_id)
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
            updated = _copy_run(run)
            updated.executor_id = existing.executor_id
            updated.execution_lease_expires_at = existing.execution_lease_expires_at
            self.runs[run.response.id] = updated
            self.messages.setdefault(run.response.thread_id, []).append((run.owner_id, message))
            self._append_event_locked(run.owner_id, run.response, event_type, payload)
            return message.model_copy(deep=True)

    async def propose_tool_call(
        self,
        run: StoredAgentRun,
        tool_call: StoredAgentToolCall,
        approval: StoredAgentApproval | None,
        executor_id: str | None = None,
    ) -> tuple[StoredAgentToolCall, StoredAgentApproval | None, bool]:
        async with self._lock:
            existing_run = self.runs.get(run.response.id)
            if existing_run is None or existing_run.owner_id != run.owner_id:
                raise KeyError(run.response.id)
            _assert_execution_owned(existing_run, executor_id)
            provider_key = (run.response.id, tool_call.provider_call_id)
            if existing_id := self.tool_call_by_provider.get(provider_key):
                existing = self.tool_calls[existing_id]
                if (
                    existing.response.tool_name != tool_call.response.tool_name
                    or existing.response.arguments_hash != tool_call.response.arguments_hash
                ):
                    raise ValueError("AGENT_TOOL_CALL_REUSED")
                if existing_run.response.status is not AgentRunStatus.STREAMING:
                    raise AgentStateConflict(_copy_run(existing_run))
                existing_run.response = run.response.model_copy(deep=True)
                existing_approval = (
                    self.approvals[self.approval_by_tool_call[existing_id]]
                    if existing_id in self.approval_by_tool_call
                    else None
                )
                return (
                    _copy_tool_call(existing),
                    _copy_approval(existing_approval) if existing_approval else None,
                    False,
                )
            if existing_run.response.status is not AgentRunStatus.STREAMING:
                raise AgentStateConflict(_copy_run(existing_run))
            existing_run.response = run.response.model_copy(deep=True)
            self.tool_calls[tool_call.response.id] = _copy_tool_call(tool_call)
            self.tool_call_by_provider[provider_key] = tool_call.response.id
            self._append_event_locked(
                run.owner_id,
                existing_run.response,
                "agent.tool.proposed",
                {"toolCall": tool_call.response.model_dump(mode="json", by_alias=True)},
            )
            if approval is not None:
                self.approvals[approval.response.id] = _copy_approval(approval)
                self.approval_by_tool_call[tool_call.response.id] = approval.response.id
                existing_run.response = existing_run.response.model_copy(
                    update={"status": AgentRunStatus.WAITING_APPROVAL}
                )
                self._append_event_locked(
                    run.owner_id,
                    existing_run.response,
                    "agent.approval.required",
                    {
                        "toolCall": tool_call.response.model_dump(mode="json", by_alias=True),
                        "approval": approval.response.model_dump(mode="json", by_alias=True),
                    },
                )
                self._append_event_locked(
                    run.owner_id,
                    existing_run.response,
                    "agent.run.waiting_approval",
                    {"status": AgentRunStatus.WAITING_APPROVAL.value},
                )
            return (
                _copy_tool_call(tool_call),
                _copy_approval(approval) if approval else None,
                True,
            )

    async def get_tool_call(self, owner_id: str, tool_call_id: str) -> StoredAgentToolCall:
        stored = self.tool_calls.get(tool_call_id)
        if stored is None or stored.owner_id != owner_id:
            raise KeyError(tool_call_id)
        return _copy_tool_call(stored)

    async def list_tool_calls(self, owner_id: str, run_id: str) -> list[StoredAgentToolCall]:
        await self.get_run(owner_id, run_id)
        return sorted(
            [
                _copy_tool_call(call)
                for call in self.tool_calls.values()
                if call.owner_id == owner_id and call.response.run_id == run_id
            ],
            key=lambda call: call.response.created_at,
        )

    async def start_tool(
        self,
        owner_id: str,
        tool_call_id: str,
        expected_run_statuses: frozenset[AgentRunStatus],
        expected_tool_statuses: frozenset[AgentToolCallStatus],
        executor_id: str | None = None,
    ) -> StoredAgentToolCall:
        async with self._lock:
            stored = self.tool_calls.get(tool_call_id)
            if stored is None or stored.owner_id != owner_id:
                raise KeyError(tool_call_id)
            run = self.runs[stored.response.run_id]
            _assert_execution_owned(run, executor_id)
            if run.response.status not in expected_run_statuses:
                raise AgentStateConflict(_copy_run(run))
            if stored.response.status not in expected_tool_statuses:
                raise ValueError("AGENT_TOOL_STATE_CONFLICT")
            stored.response = stored.response.model_copy(
                update={"status": AgentToolCallStatus.RUNNING, "started_at": utc_now()}
            )
            self._append_event_locked(
                owner_id,
                run.response,
                "agent.tool.started",
                {"toolCall": stored.response.model_dump(mode="json", by_alias=True)},
            )
            return _copy_tool_call(stored)

    async def finish_tool(
        self,
        owner_id: str,
        tool_call_id: str,
        *,
        status: AgentToolCallStatus,
        result: dict[str, object] | None,
        error_code: str | None = None,
        error_message: str | None = None,
        executor_id: str | None = None,
    ) -> StoredAgentToolCall:
        if status not in {AgentToolCallStatus.SUCCEEDED, AgentToolCallStatus.FAILED}:
            raise ValueError("AGENT_TOOL_STATE_CONFLICT")
        async with self._lock:
            stored = self.tool_calls.get(tool_call_id)
            if stored is None or stored.owner_id != owner_id:
                raise KeyError(tool_call_id)
            run = self.runs[stored.response.run_id]
            _assert_execution_owned(run, executor_id)
            if stored.response.status is not AgentToolCallStatus.RUNNING:
                if stored.response.status is status:
                    return _copy_tool_call(stored)
                if not (
                    status is AgentToolCallStatus.FAILED
                    and stored.response.status is AgentToolCallStatus.APPROVED
                ):
                    raise ValueError("AGENT_TOOL_STATE_CONFLICT")
            stored.response = stored.response.model_copy(
                update={
                    "status": status,
                    "result": result,
                    "error_code": error_code,
                    "error_message": error_message,
                    "finished_at": utc_now(),
                }
            )
            event_type = (
                "agent.tool.completed"
                if status is AgentToolCallStatus.SUCCEEDED
                else "agent.tool.failed"
            )
            self._append_event_locked(
                owner_id,
                run.response,
                event_type,
                {"toolCall": stored.response.model_dump(mode="json", by_alias=True)},
            )
            return _copy_tool_call(stored)

    async def get_approval_by_tool_call(
        self, owner_id: str, tool_call_id: str
    ) -> StoredAgentApproval:
        approval_id = self.approval_by_tool_call.get(tool_call_id)
        if approval_id is None:
            raise KeyError(tool_call_id)
        approval = self.approvals[approval_id]
        if approval.owner_id != owner_id:
            raise KeyError(tool_call_id)
        return _copy_approval(approval)

    async def list_pending_approvals(self) -> list[StoredAgentApproval]:
        return [
            _copy_approval(approval)
            for approval in self.approvals.values()
            if approval.response.status is AgentApprovalStatus.PENDING
        ]

    async def decide_approval(
        self,
        owner_id: str,
        tool_call_id: str,
        *,
        approve: bool,
        decision_metadata: dict[str, object],
        executor_id: str,
        lease_expires_at: datetime,
    ) -> AgentToolDecision:
        async with self._lock:
            approval_id = self.approval_by_tool_call.get(tool_call_id)
            if approval_id is None:
                raise KeyError(tool_call_id)
            approval = self.approvals[approval_id]
            tool_call = self.tool_calls[tool_call_id]
            if approval.owner_id != owner_id or tool_call.owner_id != owner_id:
                raise KeyError(tool_call_id)
            run = self.runs[tool_call.response.run_id]
            if approval.response.status is not AgentApprovalStatus.PENDING:
                return AgentToolDecision(
                    _copy_tool_call(tool_call),
                    _copy_approval(approval),
                    _copy_run(run),
                    False,
                    approval.response.status is AgentApprovalStatus.CONSUMED,
                )
            if approval.response.expires_at <= utc_now() or run.response.status.is_terminal:
                return self._expire_approval_locked(approval, tool_call, run)
            if run.response.status is not AgentRunStatus.WAITING_APPROVAL:
                raise AgentStateConflict(_copy_run(run))
            now = utc_now()
            approval.decision_metadata = dict(decision_metadata)
            if approve:
                approval.response = approval.response.model_copy(
                    update={
                        "status": AgentApprovalStatus.CONSUMED,
                        "decided_at": now,
                        "consumed_at": now,
                    }
                )
                tool_call.response = tool_call.response.model_copy(
                    update={"status": AgentToolCallStatus.APPROVED}
                )
                approval_event = "agent.approval.approved"
            else:
                approval.response = approval.response.model_copy(
                    update={"status": AgentApprovalStatus.REJECTED, "decided_at": now}
                )
                tool_call.response = tool_call.response.model_copy(
                    update={
                        "status": AgentToolCallStatus.REJECTED,
                        "finished_at": now,
                        "result": {"ok": False, "error": {"code": "AGENT_TOOL_REJECTED"}},
                    }
                )
                approval_event = "agent.approval.rejected"
            run.response = run.response.model_copy(update={"status": AgentRunStatus.EXECUTING_TOOL})
            run.executor_id = executor_id
            run.execution_lease_expires_at = lease_expires_at
            self._append_event_locked(
                owner_id,
                run.response,
                approval_event,
                {"approval": approval.response.model_dump(mode="json", by_alias=True)},
            )
            self._append_event_locked(
                owner_id,
                run.response,
                "agent.tool.approved" if approve else "agent.tool.rejected",
                {"toolCall": tool_call.response.model_dump(mode="json", by_alias=True)},
            )
            return AgentToolDecision(
                _copy_tool_call(tool_call),
                _copy_approval(approval),
                _copy_run(run),
                True,
                approve,
            )

    async def expire_approval(self, owner_id: str, tool_call_id: str) -> AgentToolDecision:
        async with self._lock:
            approval_id = self.approval_by_tool_call.get(tool_call_id)
            if approval_id is None:
                raise KeyError(tool_call_id)
            approval = self.approvals[approval_id]
            tool_call = self.tool_calls[tool_call_id]
            if approval.owner_id != owner_id or tool_call.owner_id != owner_id:
                raise KeyError(tool_call_id)
            run = self.runs[tool_call.response.run_id]
            if approval.response.status is not AgentApprovalStatus.PENDING:
                return AgentToolDecision(
                    _copy_tool_call(tool_call),
                    _copy_approval(approval),
                    _copy_run(run),
                    False,
                    False,
                )
            return self._expire_approval_locked(approval, tool_call, run)

    def _expire_approval_locked(
        self,
        approval: StoredAgentApproval,
        tool_call: StoredAgentToolCall,
        run: StoredAgentRun,
    ) -> AgentToolDecision:
        now = utc_now()
        approval.response = approval.response.model_copy(
            update={"status": AgentApprovalStatus.EXPIRED, "decided_at": now}
        )
        tool_call.response = tool_call.response.model_copy(
            update={"status": AgentToolCallStatus.EXPIRED, "finished_at": now}
        )
        run_expired = run.response.status is AgentRunStatus.WAITING_APPROVAL
        if run_expired:
            run.response = run.response.model_copy(
                update={"status": AgentRunStatus.EXPIRED, "finished_at": now}
            )
        self._append_event_locked(
            run.owner_id,
            run.response,
            "agent.approval.expired",
            {"approval": approval.response.model_dump(mode="json", by_alias=True)},
        )
        if run_expired:
            self._append_event_locked(
                run.owner_id,
                run.response,
                "agent.run.expired",
                {"status": AgentRunStatus.EXPIRED.value},
            )
        return AgentToolDecision(
            _copy_tool_call(tool_call),
            _copy_approval(approval),
            _copy_run(run),
            False,
            False,
        )

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
        executor_id=run.executor_id,
        execution_lease_expires_at=run.execution_lease_expires_at,
    )


def _copy_tool_call(tool_call: StoredAgentToolCall) -> StoredAgentToolCall:
    return StoredAgentToolCall(
        owner_id=tool_call.owner_id,
        provider_call_id=tool_call.provider_call_id,
        response=tool_call.response.model_copy(deep=True),
    )


def _copy_approval(approval: StoredAgentApproval) -> StoredAgentApproval:
    return StoredAgentApproval(
        owner_id=approval.owner_id,
        response=approval.response.model_copy(deep=True),
        decision_metadata=dict(approval.decision_metadata),
    )
