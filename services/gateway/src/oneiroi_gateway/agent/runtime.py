import asyncio
import hashlib
import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from uuid import uuid4

from pydantic import ValidationError

from oneiroi_common.agent import (
    AgentEventResponse,
    AgentMessageContent,
    AgentMessageRole,
    AgentRunCreate,
    AgentRunResponse,
    AgentRunStatus,
    AgentThreadResponse,
    AgentUsage,
)
from oneiroi_gateway.agent.prompts import PROMPT_VERSION, SYSTEM_INSTRUCTIONS, TOOLSET_VERSION
from oneiroi_gateway.agent.protocol import (
    AgentProvider,
    AgentProviderError,
    ProviderErrorCode,
    ProviderEventType,
    ProviderRequest,
)
from oneiroi_gateway.repositories.agent import (
    AgentRepository,
    AgentStateConflict,
    StoredAgentRun,
)
from oneiroi_gateway.repositories.studio import StudioRepository
from oneiroi_gateway.settings import GatewaySettings


class AgentRuntimeError(RuntimeError):
    def __init__(self, code: str, status_code: int, message: str) -> None:
        self.code = code
        self.status_code = status_code
        self.message = message
        super().__init__(code)


_ALLOWED_TRANSITIONS: dict[AgentRunStatus, set[AgentRunStatus]] = {
    AgentRunStatus.QUEUED: {
        AgentRunStatus.STREAMING,
        AgentRunStatus.RECOVERING,
        AgentRunStatus.CANCELLING,
        AgentRunStatus.FAILED,
    },
    AgentRunStatus.RECOVERING: {
        AgentRunStatus.STREAMING,
        AgentRunStatus.CANCELLING,
        AgentRunStatus.FAILED,
    },
    AgentRunStatus.STREAMING: {
        AgentRunStatus.WAITING_APPROVAL,
        AgentRunStatus.EXECUTING_TOOL,
        AgentRunStatus.COMPLETED,
        AgentRunStatus.CANCELLING,
        AgentRunStatus.FAILED,
    },
    AgentRunStatus.WAITING_APPROVAL: {
        AgentRunStatus.STREAMING,
        AgentRunStatus.CANCELLING,
        AgentRunStatus.EXPIRED,
        AgentRunStatus.FAILED,
    },
    AgentRunStatus.EXECUTING_TOOL: {
        AgentRunStatus.STREAMING,
        AgentRunStatus.CANCELLING,
        AgentRunStatus.FAILED,
    },
    AgentRunStatus.CANCELLING: {AgentRunStatus.CANCELLED, AgentRunStatus.FAILED},
}


def utc_now() -> datetime:
    return datetime.now(UTC)


class AgentRuntime:
    def __init__(
        self,
        repository: AgentRepository,
        studio: StudioRepository,
        provider: AgentProvider | None,
        settings: GatewaySettings,
    ) -> None:
        self.repository = repository
        self.studio = studio
        self.provider = provider
        self.settings = settings
        self._conditions: dict[str, asyncio.Condition] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._owner_locks: dict[str, asyncio.Lock] = {}
        self._user_cancelled: set[str] = set()
        self._shutting_down = False

    async def create_run(
        self,
        owner_id: str,
        payload: AgentRunCreate,
        idempotency_key: str,
    ) -> AgentRunResponse:
        if self.provider is None:
            raise AgentRuntimeError(
                "AGENT_NOT_CONFIGURED",
                503,
                "Agent provider is disabled or has not passed capability probing.",
            )
        if (
            not idempotency_key
            or len(idempotency_key) > 128
            or any(character in idempotency_key for character in "\r\n")
        ):
            raise AgentRuntimeError("INVALID_IDEMPOTENCY_KEY", 400, "Invalid Idempotency-Key.")
        await self.studio.get_conversation(owner_id, payload.conversation_id)
        if len(payload.asset_ids) > self.settings.agent_max_input_images:
            raise AgentRuntimeError("AGENT_INPUT_LIMIT_EXCEEDED", 413, "Too many input assets.")
        asset_metadata: list[dict[str, object]] = []
        for asset_id in dict.fromkeys(payload.asset_ids):
            asset = await self.studio.get_asset(owner_id, asset_id)
            asset_metadata.append(
                {
                    "id": asset.response.id,
                    "type": asset.response.type,
                    "title": asset.response.title[:200],
                    "mediaType": asset.response.media_type,
                    "width": asset.response.width,
                    "height": asset.response.height,
                    "sizeBytes": asset.response.size_bytes,
                }
            )
        thread = await self.repository.get_or_create_thread(
            owner_id, payload.conversation_id, PROMPT_VERSION
        )
        request_hash = _request_hash(payload)
        now = utc_now()
        response = AgentRunResponse(
            id=f"agent-run-{uuid4().hex[:20]}",
            threadId=thread.id,
            conversationId=payload.conversation_id,
            status=AgentRunStatus.QUEUED,
            model=self.settings.agent_model,
            provider=self.settings.agent_provider,
            transport=self.settings.agent_transport,
            reasoningEffort=self.settings.agent_reasoning_effort,
            promptVersion=PROMPT_VERSION,
            toolsetVersion=TOOLSET_VERSION,
            inputSnapshot={
                "draftSnapshot": payload.draft_snapshot.model_dump(mode="json", by_alias=True),
                "assetIds": list(dict.fromkeys(payload.asset_ids)),
                "assetMetadata": asset_metadata,
                "mode": payload.mode,
            },
            createdAt=now,
        )
        stored = StoredAgentRun(
            owner_id=owner_id,
            response=response,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
        )
        lock = self._owner_locks.setdefault(owner_id, asyncio.Lock())
        async with lock:
            try:
                stored, created = await self.repository.create_run(
                    stored, AgentMessageContent(text=payload.message)
                )
            except ValueError as exc:
                if str(exc) == "IDEMPOTENCY_KEY_REUSED":
                    raise AgentRuntimeError(
                        "IDEMPOTENCY_KEY_REUSED",
                        409,
                        "Idempotency-Key was reused with different input.",
                    ) from exc
                raise
            except RuntimeError as exc:
                if str(exc) == "AGENT_RUN_CONCURRENCY_LIMIT":
                    raise AgentRuntimeError(
                        "AGENT_RUN_CONCURRENCY_LIMIT",
                        429,
                        "Only one active Agent run is allowed per owner.",
                    ) from exc
                raise
            if created:
                self._start(stored)
        return stored.response.model_copy(deep=True)

    async def get_run(self, owner_id: str, run_id: str) -> AgentRunResponse:
        return (await self.repository.get_run(owner_id, run_id)).response

    async def get_thread(self, owner_id: str, conversation_id: str) -> AgentThreadResponse:
        await self.studio.get_conversation(owner_id, conversation_id)
        return await self.repository.get_thread_by_conversation(owner_id, conversation_id)

    async def list_messages(
        self,
        owner_id: str,
        thread_id: str,
        after_sequence: int = 0,
        limit: int = 50,
    ):
        return await self.repository.list_messages(owner_id, thread_id, after_sequence, limit)

    async def cancel(self, owner_id: str, run_id: str) -> AgentRunResponse:
        stored = await self.repository.get_run(owner_id, run_id)
        if stored.response.status.is_terminal:
            return stored.response
        if stored.response.status is not AgentRunStatus.CANCELLING:
            previous_status = stored.response.status
            stored.response = self._with_status(stored.response, AgentRunStatus.CANCELLING)
            try:
                await self.repository.transition_run(
                    stored,
                    "agent.run.cancelling",
                    {"status": AgentRunStatus.CANCELLING.value},
                    frozenset({previous_status}),
                )
            except AgentStateConflict as exc:
                if exc.latest.response.status.is_terminal:
                    return exc.latest.response
                raise AgentRuntimeError(
                    "AGENT_STATE_CONFLICT", 409, "The Agent run state changed concurrently."
                ) from exc
            await self._notify(run_id)
        self._user_cancelled.add(run_id)
        task = self._tasks.get(run_id)
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        else:
            await self._mark_cancelled(owner_id, run_id)
        return (await self.repository.get_run(owner_id, run_id)).response

    async def events(
        self,
        owner_id: str,
        run_id: str,
        after_id: int = 0,
    ) -> AsyncIterator[AgentEventResponse | None]:
        await self.repository.get_run(owner_id, run_id)
        cursor = after_id
        condition = self._conditions.setdefault(run_id, asyncio.Condition())
        last_heartbeat = asyncio.get_running_loop().time()
        while True:
            events = await self.repository.list_events(owner_id, run_id, cursor)
            if events:
                for event in events:
                    cursor = event.id
                    yield event
                continue
            snapshot = await self.repository.get_run(owner_id, run_id)
            if snapshot.response.status.is_terminal:
                return
            async with condition:
                try:
                    await asyncio.wait_for(condition.wait(), timeout=1)
                except TimeoutError:
                    now = asyncio.get_running_loop().time()
                    if now - last_heartbeat >= 15:
                        last_heartbeat = now
                        yield None

    async def recover_incomplete(self) -> list[str]:
        recovered: list[str] = []
        for stored in await self.repository.list_incomplete_runs():
            if stored.response.status is AgentRunStatus.CANCELLING:
                await self._mark_cancelled(stored.owner_id, stored.response.id)
                recovered.append(stored.response.id)
                continue
            await self._mark_failed(
                stored,
                "AGENT_RECOVERY_REQUIRED",
                "The interrupted run was terminated safely; create a new run to retry.",
            )
            recovered.append(stored.response.id)
        return recovered

    async def close(self) -> None:
        self._shutting_down = True
        tasks = list(self._tasks.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        if self.provider is not None:
            await self.provider.close()

    def _start(self, run: StoredAgentRun) -> None:
        task = asyncio.create_task(self._execute(run), name=f"agent-{run.response.id}")
        self._tasks[run.response.id] = task
        task.add_done_callback(lambda _task, run_id=run.response.id: self._tasks.pop(run_id, None))

    async def _execute(self, run: StoredAgentRun) -> None:
        try:
            previous_status = run.response.status
            run.response = self._with_status(
                run.response, AgentRunStatus.STREAMING, started_at=utc_now()
            )
            await self.repository.transition_run(
                run,
                "agent.run.started",
                {"status": AgentRunStatus.STREAMING.value},
                frozenset({previous_status}),
            )
            await self._notify(run.response.id)
            messages = await self.repository.list_messages(
                run.owner_id, run.response.thread_id, limit=20
            )
            request = ProviderRequest(
                model=run.response.model,
                instructions=SYSTEM_INSTRUCTIONS,
                input_items=_provider_input(messages, run.response.input_snapshot),
                reasoning_effort=self.settings.agent_reasoning_effort,
                max_output_tokens=self.settings.agent_max_output_tokens,
                request_id=run.response.id,
            )
            text_parts: list[str] = []
            text_length = 0
            provider_event_count = 0
            usage = AgentUsage(providerRequests=1)
            provider_failed: str | None = None
            async for event in self.provider.stream_response(request):
                provider_event_count += 1
                if provider_event_count > self.settings.agent_max_events_per_run:
                    raise AgentRuntimeError(
                        "AGENT_OUTPUT_INVALID", 422, "Agent event limit exceeded."
                    )
                if event.response_id:
                    run.response = run.response.model_copy(
                        update={"provider_response_id": event.response_id}
                    )
                if event.event_type is ProviderEventType.TEXT_DELTA:
                    delta = str(event.data.get("delta", ""))
                    if not delta:
                        continue
                    if text_length + len(delta) > 20_000:
                        raise AgentRuntimeError(
                            "AGENT_OUTPUT_INVALID", 422, "Agent output exceeded the allowed size."
                        )
                    text_parts.append(delta)
                    text_length += len(delta)
                    await self.repository.append_event(
                        run.owner_id,
                        run.response.id,
                        "agent.message.delta",
                        {"delta": delta},
                        frozenset({AgentRunStatus.STREAMING}),
                    )
                    await self._notify(run.response.id)
                elif event.event_type is ProviderEventType.TEXT_COMPLETED and not text_parts:
                    text_parts.append(str(event.data.get("text", ""))[:20_000])
                elif event.event_type is ProviderEventType.USAGE_COMPLETED:
                    usage = AgentUsage(
                        inputTokens=int(event.data.get("inputTokens", 0)),
                        outputTokens=int(event.data.get("outputTokens", 0)),
                        totalTokens=int(event.data.get("totalTokens", 0)),
                        providerRequests=1,
                    )
                elif event.event_type is ProviderEventType.TOOL_PROPOSED:
                    raise AgentRuntimeError(
                        "AGENT_TOOL_NOT_ALLOWED",
                        422,
                        "The provider proposed a tool that is not enabled in this phase.",
                    )
                elif event.event_type is ProviderEventType.RESPONSE_FAILED:
                    provider_failed = str(
                        event.data.get("code", ProviderErrorCode.PROVIDER_UNAVAILABLE.value)
                    )
            if provider_failed:
                raise AgentRuntimeError(provider_failed, 503, "The Agent provider failed.")
            try:
                content = AgentMessageContent.model_validate_json("".join(text_parts))
            except ValidationError:
                raise AgentRuntimeError(
                    "AGENT_OUTPUT_INVALID",
                    422,
                    "The Agent returned an invalid structured response.",
                ) from None
            if content.draft_proposal is not None:
                await self.repository.append_event(
                    run.owner_id,
                    run.response.id,
                    "agent.draft.proposed",
                    {
                        "draftProposal": content.draft_proposal.model_dump(
                            mode="json", by_alias=True, exclude_none=True
                        )
                    },
                    frozenset({AgentRunStatus.STREAMING}),
                )
                await self._notify(run.response.id)
            run.response = self._with_status(
                run.response.model_copy(update={"usage": usage}),
                AgentRunStatus.COMPLETED,
                finished_at=utc_now(),
            )
            message = await self.repository.finish_run(
                run,
                content,
                "agent.run.completed",
                {"status": AgentRunStatus.COMPLETED.value},
                frozenset({AgentRunStatus.STREAMING}),
            )
            run.response = run.response.model_copy(update={"output_message_id": message.id})
            await self._notify(run.response.id)
        except asyncio.CancelledError:
            if self._shutting_down and run.response.id not in self._user_cancelled:
                await asyncio.shield(
                    self._mark_failed(
                        run,
                        "AGENT_STREAM_INTERRUPTED",
                        "The Gateway stopped before the run completed.",
                    )
                )
            else:
                await asyncio.shield(self._mark_cancelled(run.owner_id, run.response.id))
            raise
        except AgentStateConflict as exc:
            if exc.latest.response.status.is_terminal:
                return
            if exc.latest.response.status is AgentRunStatus.CANCELLING:
                await self._mark_cancelled(run.owner_id, run.response.id)
                return
            await self._mark_failed(
                run,
                "AGENT_STATE_CONFLICT",
                "The Agent run state changed concurrently.",
            )
        except AgentProviderError as exc:
            await self._mark_failed(run, exc.code.value, _provider_message(exc.code))
        except AgentRuntimeError as exc:
            await self._mark_failed(run, exc.code, exc.message)
        except Exception:
            await self._mark_failed(
                run,
                "AGENT_PROVIDER_UNAVAILABLE",
                "The Agent run failed safely.",
            )

    async def _mark_failed(self, run: StoredAgentRun, code: str, message: str) -> None:
        for _ in range(3):
            latest = await self.repository.get_run(run.owner_id, run.response.id)
            if latest.response.status.is_terminal:
                return
            if latest.response.status is AgentRunStatus.CANCELLING:
                await self._mark_cancelled(run.owner_id, run.response.id)
                return
            previous_status = latest.response.status
            latest.response = self._with_status(
                latest.response.model_copy(update={"error_code": code, "error_message": message}),
                AgentRunStatus.FAILED,
                finished_at=utc_now(),
            )
            try:
                await self.repository.transition_run(
                    latest,
                    "agent.run.failed",
                    {"status": AgentRunStatus.FAILED.value, "code": code},
                    frozenset({previous_status}),
                )
            except AgentStateConflict as exc:
                if exc.latest.response.status.is_terminal:
                    return
                continue
            await self._notify(latest.response.id)
            return
        raise AgentRuntimeError(
            "AGENT_STATE_CONFLICT", 409, "The Agent run state changed concurrently."
        )

    async def _mark_cancelled(self, owner_id: str, run_id: str) -> None:
        for _ in range(4):
            latest = await self.repository.get_run(owner_id, run_id)
            if latest.response.status.is_terminal:
                return
            previous_status = latest.response.status
            if previous_status is not AgentRunStatus.CANCELLING:
                latest.response = self._with_status(latest.response, AgentRunStatus.CANCELLING)
                event_type = "agent.run.cancelling"
                payload = {"status": AgentRunStatus.CANCELLING.value}
            else:
                latest.response = self._with_status(
                    latest.response,
                    AgentRunStatus.CANCELLED,
                    finished_at=utc_now(),
                )
                event_type = "agent.run.cancelled"
                payload = {"status": AgentRunStatus.CANCELLED.value}
            try:
                await self.repository.transition_run(
                    latest,
                    event_type,
                    payload,
                    frozenset({previous_status}),
                )
            except AgentStateConflict as exc:
                if exc.latest.response.status.is_terminal:
                    return
                continue
            await self._notify(run_id)
            if latest.response.status is AgentRunStatus.CANCELLED:
                return
        raise AgentRuntimeError(
            "AGENT_STATE_CONFLICT", 409, "The Agent run state changed concurrently."
        )

    async def _notify(self, run_id: str) -> None:
        condition = self._conditions.setdefault(run_id, asyncio.Condition())
        async with condition:
            condition.notify_all()

    @staticmethod
    def _with_status(
        response: AgentRunResponse,
        status: AgentRunStatus,
        *,
        started_at: datetime | None = None,
        finished_at: datetime | None = None,
    ) -> AgentRunResponse:
        if response.status != status:
            allowed = _ALLOWED_TRANSITIONS.get(response.status, set())
            if status not in allowed:
                raise AgentRuntimeError(
                    "AGENT_STATE_CONFLICT",
                    409,
                    f"Illegal Agent run transition: {response.status.value} -> {status.value}",
                )
        updates: dict[str, object] = {"status": status}
        if started_at is not None:
            updates["started_at"] = started_at
        if finished_at is not None:
            updates["finished_at"] = finished_at
        return response.model_copy(update=updates)


def _request_hash(payload: AgentRunCreate) -> str:
    canonical = json.dumps(
        payload.model_dump(mode="json", by_alias=True),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def _provider_input(messages, snapshot: dict[str, object]) -> list[dict[str, object]]:
    items: list[dict[str, object]] = []
    for index, message in enumerate(messages):
        if message.role not in {AgentMessageRole.USER, AgentMessageRole.ASSISTANT}:
            continue
        text = message.content.text
        if index == len(messages) - 1 and message.role is AgentMessageRole.USER:
            text = json.dumps(
                {
                    "userMessage": text,
                    "creationContext": snapshot,
                },
                ensure_ascii=False,
                separators=(",", ":"),
            )
        items.append(
            {
                "role": "assistant" if message.role is AgentMessageRole.ASSISTANT else "user",
                "content": [
                    {
                        "type": (
                            "output_text"
                            if message.role is AgentMessageRole.ASSISTANT
                            else "input_text"
                        ),
                        "text": text,
                    }
                ],
            }
        )
    return items


def _provider_message(code: ProviderErrorCode) -> str:
    messages = {
        ProviderErrorCode.AUTH_FAILED: "The Agent provider credential was rejected.",
        ProviderErrorCode.RATE_LIMITED: "The Agent provider is rate limited; retry later.",
        ProviderErrorCode.CONTEXT_TOO_LARGE: "The Agent context is too large.",
        ProviderErrorCode.STREAM_INTERRUPTED: "The Agent stream was interrupted.",
        ProviderErrorCode.TOOL_ARGUMENTS_INVALID: "The Agent proposed invalid tool arguments.",
        ProviderErrorCode.OUTPUT_INVALID: "The Agent returned invalid output.",
    }
    return messages.get(code, "The Agent provider is unavailable.")
