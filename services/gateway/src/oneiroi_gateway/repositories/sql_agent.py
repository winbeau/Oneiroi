from datetime import datetime

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

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
    AgentToolRisk,
    AgentUsage,
)
from oneiroi_gateway.db.models.agent import (
    AgentApprovalModel,
    AgentEventModel,
    AgentMessageModel,
    AgentRunModel,
    AgentThreadModel,
    AgentToolCallModel,
)
from oneiroi_gateway.repositories.agent import (
    AgentExecutionOwned,
    AgentStateConflict,
    AgentToolDecision,
    StoredAgentApproval,
    StoredAgentRun,
    StoredAgentToolCall,
    utc_now,
)


class SqlAgentRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions

    async def get_or_create_thread(
        self, owner_id: str, conversation_id: str, prompt_version: str
    ) -> AgentThreadResponse:
        async with self.sessions() as session:
            existing = await session.scalar(
                select(AgentThreadModel).where(
                    AgentThreadModel.owner_id == owner_id,
                    AgentThreadModel.conversation_id == conversation_id,
                )
            )
            if existing is not None:
                return self._thread(existing)
            from uuid import uuid4

            now = utc_now()
            row = AgentThreadModel(
                id=f"agent-thread-{uuid4().hex[:20]}",
                owner_id=owner_id,
                conversation_id=conversation_id,
                status=AgentThreadStatus.ACTIVE.value,
                summary_text=None,
                summary_cursor=0,
                prompt_version=prompt_version,
                created_at=now,
                updated_at=now,
            )
            session.add(row)
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                existing = await session.scalar(
                    select(AgentThreadModel).where(
                        AgentThreadModel.owner_id == owner_id,
                        AgentThreadModel.conversation_id == conversation_id,
                    )
                )
                if existing is None:
                    raise KeyError(conversation_id) from None
                return self._thread(existing)
            return self._thread(row)

    async def get_thread(self, owner_id: str, thread_id: str) -> AgentThreadResponse:
        async with self.sessions() as session:
            row = await session.scalar(
                select(AgentThreadModel).where(
                    AgentThreadModel.id == thread_id,
                    AgentThreadModel.owner_id == owner_id,
                )
            )
        if row is None:
            raise KeyError(thread_id)
        return self._thread(row)

    async def get_thread_by_conversation(
        self, owner_id: str, conversation_id: str
    ) -> AgentThreadResponse:
        async with self.sessions() as session:
            row = await session.scalar(
                select(AgentThreadModel).where(
                    AgentThreadModel.owner_id == owner_id,
                    AgentThreadModel.conversation_id == conversation_id,
                )
            )
        if row is None:
            raise KeyError(conversation_id)
        return self._thread(row)

    async def list_messages(
        self,
        owner_id: str,
        thread_id: str,
        after_sequence: int = 0,
        limit: int = 50,
    ) -> list[AgentMessageResponse]:
        await self.get_thread(owner_id, thread_id)
        async with self.sessions() as session:
            rows = (
                await session.scalars(
                    select(AgentMessageModel)
                    .where(
                        AgentMessageModel.owner_id == owner_id,
                        AgentMessageModel.thread_id == thread_id,
                        AgentMessageModel.sequence > after_sequence,
                    )
                    .order_by(AgentMessageModel.sequence)
                    .limit(limit)
                )
            ).all()
        return [self._message(row) for row in rows]

    async def create_run(
        self,
        run: StoredAgentRun,
        user_content: AgentMessageContent,
    ) -> tuple[StoredAgentRun, bool]:
        from uuid import uuid4

        terminal = [status.value for status in AgentRunStatus if status.is_terminal]
        async with self.sessions() as session:
            try:
                async with session.begin():
                    existing = await session.scalar(
                        select(AgentRunModel).where(
                            AgentRunModel.owner_id == run.owner_id,
                            AgentRunModel.idempotency_key == run.idempotency_key,
                        )
                    )
                    if existing is not None:
                        if existing.request_hash != run.request_hash:
                            raise ValueError("IDEMPOTENCY_KEY_REUSED")
                        return self._stored_run(existing), False
                    active = await session.scalar(
                        select(AgentRunModel.id).where(
                            AgentRunModel.owner_id == run.owner_id,
                            AgentRunModel.status.not_in(terminal),
                        )
                    )
                    if active is not None:
                        raise RuntimeError("AGENT_RUN_CONCURRENCY_LIMIT")
                    thread = await session.scalar(
                        select(AgentThreadModel)
                        .where(
                            AgentThreadModel.id == run.response.thread_id,
                            AgentThreadModel.owner_id == run.owner_id,
                        )
                        .with_for_update()
                    )
                    if thread is None:
                        raise KeyError(run.response.thread_id)
                    message_sequence = (
                        await session.scalar(
                            select(func.coalesce(func.max(AgentMessageModel.sequence), 0)).where(
                                AgentMessageModel.thread_id == run.response.thread_id
                            )
                        )
                    ) + 1
                    now = utc_now()
                    session.add(self._run_model(run))
                    await session.flush()
                    session.add(
                        AgentMessageModel(
                            id=f"agent-message-{uuid4().hex[:20]}",
                            owner_id=run.owner_id,
                            thread_id=run.response.thread_id,
                            run_id=run.response.id,
                            sequence=message_sequence,
                            role=AgentMessageRole.USER.value,
                            content_json=user_content.model_dump(mode="json", by_alias=True),
                            status=AgentMessageStatus.COMPLETED.value,
                            provider_item_id=None,
                            created_at=now,
                            completed_at=now,
                        )
                    )
                    session.add(
                        AgentEventModel(
                            owner_id=run.owner_id,
                            run_id=run.response.id,
                            thread_id=run.response.thread_id,
                            event_type="agent.run.queued",
                            sequence=1,
                            payload_json={"status": run.response.status.value},
                            created_at=now,
                        )
                    )
                    thread.updated_at = now
                return _copy_run(run), True
            except IntegrityError:
                await session.rollback()
                existing = await session.scalar(
                    select(AgentRunModel).where(
                        AgentRunModel.owner_id == run.owner_id,
                        AgentRunModel.idempotency_key == run.idempotency_key,
                    )
                )
                if existing is not None:
                    if existing.request_hash != run.request_hash:
                        raise ValueError("IDEMPOTENCY_KEY_REUSED") from None
                    return self._stored_run(existing), False
                active = await session.scalar(
                    select(AgentRunModel.id).where(
                        AgentRunModel.owner_id == run.owner_id,
                        AgentRunModel.status.not_in(terminal),
                    )
                )
                if active is not None:
                    raise RuntimeError("AGENT_RUN_CONCURRENCY_LIMIT") from None
                raise

    async def get_run(self, owner_id: str, run_id: str) -> StoredAgentRun:
        async with self.sessions() as session:
            row = await session.scalar(
                select(AgentRunModel).where(
                    AgentRunModel.id == run_id,
                    AgentRunModel.owner_id == owner_id,
                )
            )
        if row is None:
            raise KeyError(run_id)
        return self._stored_run(row)

    async def list_incomplete_runs(self) -> list[StoredAgentRun]:
        terminal = [status.value for status in AgentRunStatus if status.is_terminal]
        async with self.sessions() as session:
            rows = (
                await session.scalars(
                    select(AgentRunModel).where(AgentRunModel.status.not_in(terminal))
                )
            ).all()
        return [self._stored_run(row) for row in rows]

    async def list_recoverable_runs(self, now: datetime) -> list[StoredAgentRun]:
        terminal = [status.value for status in AgentRunStatus if status.is_terminal]
        async with self.sessions() as session:
            rows = (
                await session.scalars(
                    select(AgentRunModel).where(
                        AgentRunModel.status.not_in(terminal),
                        or_(
                            AgentRunModel.executor_id.is_(None),
                            AgentRunModel.execution_lease_expires_at.is_(None),
                            AgentRunModel.execution_lease_expires_at <= now,
                        ),
                    )
                )
            ).all()
        return [self._stored_run(row) for row in rows]

    async def claim_run_execution(
        self,
        owner_id: str,
        run_id: str,
        executor_id: str,
        lease_expires_at: datetime,
    ) -> StoredAgentRun:
        async with self.sessions() as session, session.begin():
            row = await session.scalar(
                select(AgentRunModel)
                .where(
                    AgentRunModel.id == run_id,
                    AgentRunModel.owner_id == owner_id,
                )
                .with_for_update()
            )
            if row is None:
                raise KeyError(run_id)
            if (
                row.executor_id not in {None, executor_id}
                and row.execution_lease_expires_at is not None
                and row.execution_lease_expires_at > utc_now()
            ):
                raise AgentExecutionOwned(self._stored_run(row))
            row.executor_id = executor_id
            row.execution_lease_expires_at = lease_expires_at
            await session.flush()
            return self._stored_run(row)

    async def renew_run_execution(
        self,
        owner_id: str,
        run_id: str,
        executor_id: str,
        lease_expires_at: datetime,
    ) -> StoredAgentRun:
        async with self.sessions() as session, session.begin():
            row = await session.scalar(
                select(AgentRunModel)
                .where(
                    AgentRunModel.id == run_id,
                    AgentRunModel.owner_id == owner_id,
                )
                .with_for_update()
            )
            if row is None:
                raise KeyError(run_id)
            if (
                row.executor_id != executor_id
                or row.execution_lease_expires_at is None
                or row.execution_lease_expires_at <= utc_now()
            ):
                raise AgentExecutionOwned(self._stored_run(row))
            row.execution_lease_expires_at = lease_expires_at
            await session.flush()
            return self._stored_run(row)

    async def release_run_execution(
        self, owner_id: str, run_id: str, executor_id: str
    ) -> StoredAgentRun:
        async with self.sessions() as session, session.begin():
            row = await session.scalar(
                select(AgentRunModel)
                .where(
                    AgentRunModel.id == run_id,
                    AgentRunModel.owner_id == owner_id,
                )
                .with_for_update()
            )
            if row is None:
                raise KeyError(run_id)
            if row.executor_id == executor_id:
                row.executor_id = None
                row.execution_lease_expires_at = None
                await session.flush()
            return self._stored_run(row)

    async def record_active_seconds(
        self,
        owner_id: str,
        run_id: str,
        executor_id: str,
        seconds: float,
    ) -> StoredAgentRun:
        async with self.sessions() as session, session.begin():
            row = await session.scalar(
                select(AgentRunModel)
                .where(
                    AgentRunModel.id == run_id,
                    AgentRunModel.owner_id == owner_id,
                )
                .with_for_update()
            )
            if row is None:
                raise KeyError(run_id)
            self._assert_execution_owned(row, executor_id)
            row.active_duration_seconds += max(0.0, seconds)
            await session.flush()
            return self._stored_run(row)

    async def consume_provider_event(
        self,
        owner_id: str,
        run_id: str,
        executor_id: str,
        maximum: int,
    ) -> StoredAgentRun:
        async with self.sessions() as session, session.begin():
            row = await session.scalar(
                select(AgentRunModel)
                .where(
                    AgentRunModel.id == run_id,
                    AgentRunModel.owner_id == owner_id,
                )
                .with_for_update()
            )
            if row is None:
                raise KeyError(run_id)
            self._assert_execution_owned(row, executor_id)
            if row.provider_event_count >= maximum:
                raise ValueError("AGENT_EVENT_LIMIT_EXCEEDED")
            row.provider_event_count += 1
            await session.flush()
            return self._stored_run(row)

    async def transition_run(
        self,
        run: StoredAgentRun,
        event_type: str,
        payload: dict[str, object],
        expected_statuses: frozenset[AgentRunStatus],
        executor_id: str | None = None,
    ) -> AgentEventResponse:
        async with self.sessions() as session:
            async with session.begin():
                row = await session.scalar(
                    select(AgentRunModel)
                    .where(
                        AgentRunModel.id == run.response.id,
                        AgentRunModel.owner_id == run.owner_id,
                    )
                    .with_for_update()
                )
                if row is None:
                    raise KeyError(run.response.id)
                self._assert_execution_owned(row, executor_id)
                if AgentRunStatus(row.status) not in expected_statuses:
                    raise AgentStateConflict(self._stored_run(row))
                self._apply_run(row, run)
                event = await self._add_event(session, run, event_type, payload)
            return self._event(event)

    async def append_event(
        self,
        owner_id: str,
        run_id: str,
        event_type: str,
        payload: dict[str, object],
        expected_statuses: frozenset[AgentRunStatus] | None = None,
        executor_id: str | None = None,
    ) -> AgentEventResponse:
        run = await self.get_run(owner_id, run_id)
        async with self.sessions() as session:
            async with session.begin():
                row = await session.scalar(
                    select(AgentRunModel)
                    .where(
                        AgentRunModel.id == run_id,
                        AgentRunModel.owner_id == owner_id,
                    )
                    .with_for_update()
                )
                if row is None:
                    raise KeyError(run_id)
                self._assert_execution_owned(row, executor_id)
                if (
                    expected_statuses is not None
                    and AgentRunStatus(row.status) not in expected_statuses
                ):
                    raise AgentStateConflict(self._stored_run(row))
                event = await self._add_event(session, run, event_type, payload)
            return self._event(event)

    async def finish_run(
        self,
        run: StoredAgentRun,
        assistant_content: AgentMessageContent,
        event_type: str,
        payload: dict[str, object],
        expected_statuses: frozenset[AgentRunStatus],
        executor_id: str | None = None,
    ) -> AgentMessageResponse:
        from uuid import uuid4

        async with self.sessions() as session:
            async with session.begin():
                row = await session.scalar(
                    select(AgentRunModel)
                    .where(
                        AgentRunModel.id == run.response.id,
                        AgentRunModel.owner_id == run.owner_id,
                    )
                    .with_for_update()
                )
                if row is None:
                    raise KeyError(run.response.id)
                self._assert_execution_owned(row, executor_id)
                if AgentRunStatus(row.status) not in expected_statuses:
                    raise AgentStateConflict(self._stored_run(row))
                if row.output_message_id is not None:
                    raise AgentStateConflict(self._stored_run(row))
                thread = await session.scalar(
                    select(AgentThreadModel)
                    .where(
                        AgentThreadModel.id == run.response.thread_id,
                        AgentThreadModel.owner_id == run.owner_id,
                    )
                    .with_for_update()
                )
                if thread is None:
                    raise KeyError(run.response.thread_id)
                sequence = (
                    await session.scalar(
                        select(func.coalesce(func.max(AgentMessageModel.sequence), 0)).where(
                            AgentMessageModel.thread_id == run.response.thread_id
                        )
                    )
                ) + 1
                now = utc_now()
                message = AgentMessageModel(
                    id=f"agent-message-{uuid4().hex[:20]}",
                    owner_id=run.owner_id,
                    thread_id=run.response.thread_id,
                    run_id=run.response.id,
                    sequence=sequence,
                    role=AgentMessageRole.ASSISTANT.value,
                    content_json=assistant_content.model_dump(mode="json", by_alias=True),
                    status=AgentMessageStatus.COMPLETED.value,
                    provider_item_id=None,
                    created_at=now,
                    completed_at=now,
                )
                session.add(message)
                run.response = run.response.model_copy(update={"output_message_id": message.id})
                self._apply_run(row, run)
                await self._add_event(session, run, event_type, payload)
                thread.updated_at = now
            return self._message(message)

    async def propose_tool_call(
        self,
        run: StoredAgentRun,
        tool_call: StoredAgentToolCall,
        approval: StoredAgentApproval | None,
        executor_id: str | None = None,
    ) -> tuple[StoredAgentToolCall, StoredAgentApproval | None, bool]:
        async with self.sessions() as session, session.begin():
            run_row = await session.scalar(
                select(AgentRunModel)
                .where(
                    AgentRunModel.id == run.response.id,
                    AgentRunModel.owner_id == run.owner_id,
                )
                .with_for_update()
            )
            if run_row is None:
                raise KeyError(run.response.id)
            self._assert_execution_owned(run_row, executor_id)
            existing = await session.scalar(
                select(AgentToolCallModel).where(
                    AgentToolCallModel.run_id == run.response.id,
                    AgentToolCallModel.provider_call_id == tool_call.provider_call_id,
                )
            )
            if existing is not None:
                if (
                    existing.tool_name != tool_call.response.tool_name
                    or existing.arguments_hash != tool_call.response.arguments_hash
                ):
                    raise ValueError("AGENT_TOOL_CALL_REUSED")
                if AgentRunStatus(run_row.status) is not AgentRunStatus.STREAMING:
                    raise AgentStateConflict(self._stored_run(run_row))
                self._apply_run(run_row, run)
                approval_row = await session.scalar(
                    select(AgentApprovalModel).where(AgentApprovalModel.tool_call_id == existing.id)
                )
                return (
                    self._stored_tool_call(existing),
                    self._stored_approval(approval_row) if approval_row else None,
                    False,
                )
            if AgentRunStatus(run_row.status) is not AgentRunStatus.STREAMING:
                raise AgentStateConflict(self._stored_run(run_row))
            self._apply_run(run_row, run)
            call_row = self._tool_call_model(tool_call)
            session.add(call_row)
            await session.flush()
            await self._add_event(
                session,
                run,
                "agent.tool.proposed",
                {"toolCall": tool_call.response.model_dump(mode="json", by_alias=True)},
            )
            if approval is not None:
                approval_row = self._approval_model(approval)
                session.add(approval_row)
                run.response = run.response.model_copy(
                    update={"status": AgentRunStatus.WAITING_APPROVAL}
                )
                self._apply_run(run_row, run)
                await self._add_event(
                    session,
                    run,
                    "agent.approval.required",
                    {
                        "toolCall": tool_call.response.model_dump(mode="json", by_alias=True),
                        "approval": approval.response.model_dump(mode="json", by_alias=True),
                    },
                )
                await self._add_event(
                    session,
                    run,
                    "agent.run.waiting_approval",
                    {"status": AgentRunStatus.WAITING_APPROVAL.value},
                )
            return tool_call, approval, True

    async def get_tool_call(self, owner_id: str, tool_call_id: str) -> StoredAgentToolCall:
        async with self.sessions() as session:
            row = await session.scalar(
                select(AgentToolCallModel).where(
                    AgentToolCallModel.id == tool_call_id,
                    AgentToolCallModel.owner_id == owner_id,
                )
            )
        if row is None:
            raise KeyError(tool_call_id)
        return self._stored_tool_call(row)

    async def list_tool_calls(self, owner_id: str, run_id: str) -> list[StoredAgentToolCall]:
        await self.get_run(owner_id, run_id)
        async with self.sessions() as session:
            rows = (
                await session.scalars(
                    select(AgentToolCallModel)
                    .where(
                        AgentToolCallModel.owner_id == owner_id,
                        AgentToolCallModel.run_id == run_id,
                    )
                    .order_by(AgentToolCallModel.created_at, AgentToolCallModel.id)
                )
            ).all()
        return [self._stored_tool_call(row) for row in rows]

    async def start_tool(
        self,
        owner_id: str,
        tool_call_id: str,
        expected_run_statuses: frozenset[AgentRunStatus],
        expected_tool_statuses: frozenset[AgentToolCallStatus],
        executor_id: str | None = None,
    ) -> StoredAgentToolCall:
        async with self.sessions() as session:
            async with session.begin():
                call_row = await session.scalar(
                    select(AgentToolCallModel)
                    .where(
                        AgentToolCallModel.id == tool_call_id,
                        AgentToolCallModel.owner_id == owner_id,
                    )
                    .with_for_update()
                )
                if call_row is None:
                    raise KeyError(tool_call_id)
                run_row = await session.scalar(
                    select(AgentRunModel)
                    .where(
                        AgentRunModel.id == call_row.run_id,
                        AgentRunModel.owner_id == owner_id,
                    )
                    .with_for_update()
                )
                if run_row is None:
                    raise KeyError(call_row.run_id)
                self._assert_execution_owned(run_row, executor_id)
                if AgentRunStatus(run_row.status) not in expected_run_statuses:
                    raise AgentStateConflict(self._stored_run(run_row))
                if AgentToolCallStatus(call_row.status) not in expected_tool_statuses:
                    raise ValueError("AGENT_TOOL_STATE_CONFLICT")
                call_row.status = AgentToolCallStatus.RUNNING.value
                call_row.started_at = utc_now()
                await session.flush()
                stored = self._stored_tool_call(call_row)
                await self._add_event(
                    session,
                    self._stored_run(run_row),
                    "agent.tool.started",
                    {"toolCall": stored.response.model_dump(mode="json", by_alias=True)},
                )
            return stored

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
        async with self.sessions() as session:
            async with session.begin():
                call_row = await session.scalar(
                    select(AgentToolCallModel)
                    .where(
                        AgentToolCallModel.id == tool_call_id,
                        AgentToolCallModel.owner_id == owner_id,
                    )
                    .with_for_update()
                )
                if call_row is None:
                    raise KeyError(tool_call_id)
                run_row = await session.scalar(
                    select(AgentRunModel)
                    .where(
                        AgentRunModel.id == call_row.run_id,
                        AgentRunModel.owner_id == owner_id,
                    )
                    .with_for_update()
                )
                if run_row is None:
                    raise KeyError(call_row.run_id)
                self._assert_execution_owned(run_row, executor_id)
                current = AgentToolCallStatus(call_row.status)
                if current is not AgentToolCallStatus.RUNNING:
                    if current is status:
                        return self._stored_tool_call(call_row)
                    if not (
                        status is AgentToolCallStatus.FAILED
                        and current is AgentToolCallStatus.APPROVED
                    ):
                        raise ValueError("AGENT_TOOL_STATE_CONFLICT")
                call_row.status = status.value
                call_row.result_json = result
                call_row.error_code = error_code
                call_row.error_message = error_message
                call_row.finished_at = utc_now()
                await session.flush()
                stored = self._stored_tool_call(call_row)
                event_type = (
                    "agent.tool.completed"
                    if status is AgentToolCallStatus.SUCCEEDED
                    else "agent.tool.failed"
                )
                await self._add_event(
                    session,
                    self._stored_run(run_row),
                    event_type,
                    {"toolCall": stored.response.model_dump(mode="json", by_alias=True)},
                )
            return stored

    async def get_approval_by_tool_call(
        self, owner_id: str, tool_call_id: str
    ) -> StoredAgentApproval:
        async with self.sessions() as session:
            row = await session.scalar(
                select(AgentApprovalModel).where(
                    AgentApprovalModel.tool_call_id == tool_call_id,
                    AgentApprovalModel.owner_id == owner_id,
                )
            )
        if row is None:
            raise KeyError(tool_call_id)
        return self._stored_approval(row)

    async def list_pending_approvals(self) -> list[StoredAgentApproval]:
        async with self.sessions() as session:
            rows = (
                await session.scalars(
                    select(AgentApprovalModel).where(
                        AgentApprovalModel.status == AgentApprovalStatus.PENDING.value
                    )
                )
            ).all()
        return [self._stored_approval(row) for row in rows]

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
        async with self.sessions() as session, session.begin():
            approval_row, call_row, run_row = await self._locked_approval_rows(
                session, owner_id, tool_call_id
            )
            current = AgentApprovalStatus(approval_row.status)
            if current is not AgentApprovalStatus.PENDING:
                return AgentToolDecision(
                    self._stored_tool_call(call_row),
                    self._stored_approval(approval_row),
                    self._stored_run(run_row),
                    False,
                    current is AgentApprovalStatus.CONSUMED,
                )
            if approval_row.expires_at <= utc_now() or AgentRunStatus(run_row.status).is_terminal:
                return await self._expire_approval_rows(session, approval_row, call_row, run_row)
            if AgentRunStatus(run_row.status) is not AgentRunStatus.WAITING_APPROVAL:
                raise AgentStateConflict(self._stored_run(run_row))
            now = utc_now()
            approval_row.decision_metadata_json = decision_metadata
            if approve:
                approval_row.status = AgentApprovalStatus.CONSUMED.value
                approval_row.decided_at = now
                approval_row.consumed_at = now
                call_row.status = AgentToolCallStatus.APPROVED.value
                approval_event = "agent.approval.approved"
                tool_event = "agent.tool.approved"
            else:
                approval_row.status = AgentApprovalStatus.REJECTED.value
                approval_row.decided_at = now
                call_row.status = AgentToolCallStatus.REJECTED.value
                call_row.finished_at = now
                call_row.result_json = {
                    "ok": False,
                    "error": {"code": "AGENT_TOOL_REJECTED"},
                }
                approval_event = "agent.approval.rejected"
                tool_event = "agent.tool.rejected"
            run_row.status = AgentRunStatus.EXECUTING_TOOL.value
            run_row.executor_id = executor_id
            run_row.execution_lease_expires_at = lease_expires_at
            await session.flush()
            stored_run = self._stored_run(run_row)
            stored_call = self._stored_tool_call(call_row)
            stored_approval = self._stored_approval(approval_row)
            await self._add_event(
                session,
                stored_run,
                approval_event,
                {"approval": stored_approval.response.model_dump(mode="json", by_alias=True)},
            )
            await self._add_event(
                session,
                stored_run,
                tool_event,
                {"toolCall": stored_call.response.model_dump(mode="json", by_alias=True)},
            )
            return AgentToolDecision(
                stored_call,
                stored_approval,
                stored_run,
                True,
                approve,
            )

    async def expire_approval(self, owner_id: str, tool_call_id: str) -> AgentToolDecision:
        async with self.sessions() as session, session.begin():
            approval_row, call_row, run_row = await self._locked_approval_rows(
                session, owner_id, tool_call_id
            )
            if AgentApprovalStatus(approval_row.status) is not AgentApprovalStatus.PENDING:
                return AgentToolDecision(
                    self._stored_tool_call(call_row),
                    self._stored_approval(approval_row),
                    self._stored_run(run_row),
                    False,
                    False,
                )
            return await self._expire_approval_rows(session, approval_row, call_row, run_row)

    async def _locked_approval_rows(
        self,
        session: AsyncSession,
        owner_id: str,
        tool_call_id: str,
    ) -> tuple[AgentApprovalModel, AgentToolCallModel, AgentRunModel]:
        approval_row = await session.scalar(
            select(AgentApprovalModel)
            .where(
                AgentApprovalModel.tool_call_id == tool_call_id,
                AgentApprovalModel.owner_id == owner_id,
            )
            .with_for_update()
        )
        if approval_row is None:
            raise KeyError(tool_call_id)
        call_row = await session.scalar(
            select(AgentToolCallModel)
            .where(
                AgentToolCallModel.id == tool_call_id,
                AgentToolCallModel.owner_id == owner_id,
            )
            .with_for_update()
        )
        if call_row is None:
            raise KeyError(tool_call_id)
        run_row = await session.scalar(
            select(AgentRunModel)
            .where(
                AgentRunModel.id == call_row.run_id,
                AgentRunModel.owner_id == owner_id,
            )
            .with_for_update()
        )
        if run_row is None:
            raise KeyError(call_row.run_id)
        return approval_row, call_row, run_row

    async def _expire_approval_rows(
        self,
        session: AsyncSession,
        approval_row: AgentApprovalModel,
        call_row: AgentToolCallModel,
        run_row: AgentRunModel,
    ) -> AgentToolDecision:
        now = utc_now()
        approval_row.status = AgentApprovalStatus.EXPIRED.value
        approval_row.decided_at = now
        call_row.status = AgentToolCallStatus.EXPIRED.value
        call_row.finished_at = now
        run_expired = AgentRunStatus(run_row.status) is AgentRunStatus.WAITING_APPROVAL
        if run_expired:
            run_row.status = AgentRunStatus.EXPIRED.value
            run_row.finished_at = now
        await session.flush()
        stored_run = self._stored_run(run_row)
        stored_call = self._stored_tool_call(call_row)
        stored_approval = self._stored_approval(approval_row)
        await self._add_event(
            session,
            stored_run,
            "agent.approval.expired",
            {"approval": stored_approval.response.model_dump(mode="json", by_alias=True)},
        )
        if run_expired:
            await self._add_event(
                session,
                stored_run,
                "agent.run.expired",
                {"status": AgentRunStatus.EXPIRED.value},
            )
        return AgentToolDecision(
            stored_call,
            stored_approval,
            stored_run,
            False,
            False,
        )

    async def list_events(
        self, owner_id: str, run_id: str, after_id: int = 0, limit: int = 200
    ) -> list[AgentEventResponse]:
        await self.get_run(owner_id, run_id)
        async with self.sessions() as session:
            rows = (
                await session.scalars(
                    select(AgentEventModel)
                    .where(
                        AgentEventModel.owner_id == owner_id,
                        AgentEventModel.run_id == run_id,
                        AgentEventModel.id > after_id,
                    )
                    .order_by(AgentEventModel.id)
                    .limit(limit)
                )
            ).all()
        return [self._event(row) for row in rows]

    async def _add_event(
        self,
        session: AsyncSession,
        run: StoredAgentRun,
        event_type: str,
        payload: dict[str, object],
    ) -> AgentEventModel:
        sequence = (
            await session.scalar(
                select(func.coalesce(func.max(AgentEventModel.sequence), 0)).where(
                    AgentEventModel.run_id == run.response.id
                )
            )
        ) + 1
        event = AgentEventModel(
            owner_id=run.owner_id,
            run_id=run.response.id,
            thread_id=run.response.thread_id,
            event_type=event_type,
            sequence=sequence,
            payload_json=payload,
            created_at=utc_now(),
        )
        session.add(event)
        await session.flush()
        return event

    def _assert_execution_owned(self, row: AgentRunModel, executor_id: str | None) -> None:
        if executor_id is None:
            return
        if (
            row.executor_id != executor_id
            or row.execution_lease_expires_at is None
            or row.execution_lease_expires_at <= utc_now()
        ):
            raise AgentExecutionOwned(self._stored_run(row))

    @staticmethod
    def _apply_run(row: AgentRunModel, run: StoredAgentRun) -> None:
        response = run.response
        row.status = response.status.value
        row.usage_json = response.usage.model_dump(mode="json", by_alias=True)
        row.provider_response_id = response.provider_response_id
        row.error_code = response.error_code
        row.error_message = response.error_message
        row.output_message_id = response.output_message_id
        row.started_at = response.started_at
        row.finished_at = response.finished_at

    @staticmethod
    def _run_model(run: StoredAgentRun) -> AgentRunModel:
        response = run.response
        return AgentRunModel(
            id=response.id,
            owner_id=run.owner_id,
            thread_id=response.thread_id,
            conversation_id=response.conversation_id,
            status=response.status.value,
            model=response.model,
            provider=response.provider,
            transport=response.transport,
            reasoning_effort=response.reasoning_effort,
            prompt_version=response.prompt_version,
            toolset_version=response.toolset_version,
            input_snapshot_json=response.input_snapshot,
            usage_json=response.usage.model_dump(mode="json", by_alias=True),
            provider_response_id=response.provider_response_id,
            error_code=response.error_code,
            error_message=response.error_message,
            output_message_id=response.output_message_id,
            idempotency_key=run.idempotency_key,
            request_hash=run.request_hash,
            created_at=response.created_at,
            started_at=response.started_at,
            finished_at=response.finished_at,
            executor_id=run.executor_id,
            execution_lease_expires_at=run.execution_lease_expires_at,
            active_duration_seconds=run.active_duration_seconds,
            provider_event_count=run.provider_event_count,
        )

    @staticmethod
    def _stored_run(row: AgentRunModel) -> StoredAgentRun:
        response = AgentRunResponse(
            id=row.id,
            threadId=row.thread_id,
            conversationId=row.conversation_id,
            status=AgentRunStatus(row.status),
            model=row.model,
            provider=row.provider,
            transport=row.transport,
            reasoningEffort=row.reasoning_effort,
            promptVersion=row.prompt_version,
            toolsetVersion=row.toolset_version,
            inputSnapshot=row.input_snapshot_json,
            usage=AgentUsage.model_validate(row.usage_json),
            providerResponseId=row.provider_response_id,
            errorCode=row.error_code,
            errorMessage=row.error_message,
            outputMessageId=row.output_message_id,
            createdAt=row.created_at,
            startedAt=row.started_at,
            finishedAt=row.finished_at,
        )
        return StoredAgentRun(
            owner_id=row.owner_id,
            response=response,
            idempotency_key=row.idempotency_key,
            request_hash=row.request_hash,
            executor_id=row.executor_id,
            execution_lease_expires_at=row.execution_lease_expires_at,
            active_duration_seconds=row.active_duration_seconds,
            provider_event_count=row.provider_event_count,
        )

    @staticmethod
    def _thread(row: AgentThreadModel) -> AgentThreadResponse:
        return AgentThreadResponse(
            id=row.id,
            conversationId=row.conversation_id,
            status=AgentThreadStatus(row.status),
            summaryText=row.summary_text,
            summaryCursor=row.summary_cursor,
            promptVersion=row.prompt_version,
            createdAt=row.created_at,
            updatedAt=row.updated_at,
        )

    @staticmethod
    def _message(row: AgentMessageModel) -> AgentMessageResponse:
        return AgentMessageResponse(
            id=row.id,
            threadId=row.thread_id,
            runId=row.run_id,
            sequence=row.sequence,
            role=AgentMessageRole(row.role),
            content=AgentMessageContent.model_validate(row.content_json),
            status=AgentMessageStatus(row.status),
            providerItemId=row.provider_item_id,
            createdAt=row.created_at,
            completedAt=row.completed_at,
        )

    @staticmethod
    def _tool_call_model(tool_call: StoredAgentToolCall) -> AgentToolCallModel:
        response = tool_call.response
        return AgentToolCallModel(
            id=response.id,
            provider_call_id=tool_call.provider_call_id,
            owner_id=tool_call.owner_id,
            run_id=response.run_id,
            tool_name=response.tool_name,
            tool_version=response.tool_version,
            risk=response.risk.value,
            arguments_json=response.arguments,
            arguments_hash=response.arguments_hash,
            status=response.status.value,
            result_json=response.result,
            resource_type=response.resource_type,
            resource_id=response.resource_id,
            error_code=response.error_code,
            error_message=response.error_message,
            created_at=response.created_at,
            started_at=response.started_at,
            finished_at=response.finished_at,
        )

    @staticmethod
    def _stored_tool_call(row: AgentToolCallModel) -> StoredAgentToolCall:
        return StoredAgentToolCall(
            owner_id=row.owner_id,
            provider_call_id=row.provider_call_id or row.id,
            response=AgentToolCallResponse(
                id=row.id,
                runId=row.run_id,
                toolName=row.tool_name,
                toolVersion=row.tool_version,
                risk=AgentToolRisk(row.risk),
                arguments=row.arguments_json,
                argumentsHash=row.arguments_hash,
                status=AgentToolCallStatus(row.status),
                result=row.result_json,
                resourceType=row.resource_type,
                resourceId=row.resource_id,
                errorCode=row.error_code,
                errorMessage=row.error_message,
                createdAt=row.created_at,
                startedAt=row.started_at,
                finishedAt=row.finished_at,
            ),
        )

    @staticmethod
    def _approval_model(approval: StoredAgentApproval) -> AgentApprovalModel:
        response = approval.response
        return AgentApprovalModel(
            id=response.id,
            owner_id=approval.owner_id,
            run_id=response.run_id,
            tool_call_id=response.tool_call_id,
            arguments_hash=response.arguments_hash,
            status=response.status.value,
            estimated_cost=response.estimated_cost,
            expires_at=response.expires_at,
            decided_at=response.decided_at,
            consumed_at=response.consumed_at,
            decision_metadata_json=approval.decision_metadata,
        )

    @staticmethod
    def _stored_approval(row: AgentApprovalModel) -> StoredAgentApproval:
        return StoredAgentApproval(
            owner_id=row.owner_id,
            response=AgentApprovalResponse(
                id=row.id,
                runId=row.run_id,
                toolCallId=row.tool_call_id,
                argumentsHash=row.arguments_hash,
                status=AgentApprovalStatus(row.status),
                estimatedCost=row.estimated_cost,
                expiresAt=row.expires_at,
                decidedAt=row.decided_at,
                consumedAt=row.consumed_at,
            ),
            decision_metadata=row.decision_metadata_json,
        )

    @staticmethod
    def _event(row: AgentEventModel) -> AgentEventResponse:
        return AgentEventResponse(
            id=row.id,
            runId=row.run_id,
            threadId=row.thread_id,
            eventType=row.event_type,
            sequence=row.sequence,
            payload=row.payload_json,
            createdAt=row.created_at,
        )


def _copy_run(run: StoredAgentRun) -> StoredAgentRun:
    return StoredAgentRun(
        owner_id=run.owner_id,
        response=run.response.model_copy(deep=True),
        idempotency_key=run.idempotency_key,
        request_hash=run.request_hash,
    )
