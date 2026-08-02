from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

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
    AgentUsage,
)
from oneiroi_gateway.db.models.agent import (
    AgentEventModel,
    AgentMessageModel,
    AgentRunModel,
    AgentThreadModel,
)
from oneiroi_gateway.repositories.agent import (
    AgentStateConflict,
    StoredAgentRun,
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

    async def transition_run(
        self,
        run: StoredAgentRun,
        event_type: str,
        payload: dict[str, object],
        expected_statuses: frozenset[AgentRunStatus],
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
