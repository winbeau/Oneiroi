import asyncio
import hashlib
import json
from collections.abc import AsyncIterator, Awaitable
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from functools import partial
from uuid import uuid4

from pydantic import ValidationError

from oneiroi_common.agent import (
    AgentApprovalDecision,
    AgentApprovalResponse,
    AgentApprovalStatus,
    AgentEventResponse,
    AgentMessageContent,
    AgentMessageRole,
    AgentRunCreate,
    AgentRunResponse,
    AgentRunStatus,
    AgentThreadResponse,
    AgentToolCallResponse,
    AgentToolCallStatus,
    AgentToolDecisionResponse,
    AgentUsage,
)
from oneiroi_common.studio import AssetResponse
from oneiroi_gateway.agent.prompts import PROMPT_VERSION, SYSTEM_INSTRUCTIONS, TOOLSET_VERSION
from oneiroi_gateway.agent.protocol import (
    AgentProvider,
    AgentProviderError,
    ProviderErrorCode,
    ProviderEvent,
    ProviderEventType,
    ProviderRequest,
)
from oneiroi_gateway.agent.registry import (
    ToolExecutionContext,
    ToolRegistry,
    builtin_tool_registry,
    canonical_arguments,
)
from oneiroi_gateway.repositories.agent import (
    AgentExecutionOwned,
    AgentRepository,
    AgentStateConflict,
    AgentToolDecision,
    StoredAgentApproval,
    StoredAgentRun,
    StoredAgentToolCall,
)
from oneiroi_gateway.repositories.studio import StudioRepository
from oneiroi_gateway.services.artifact_service import ArtifactService
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
        tool_registry: ToolRegistry | None = None,
        *,
        tools_available: bool | None = None,
        artifacts: ArtifactService | None = None,
        image_input_available: bool = False,
        image_generation_available: bool = False,
    ) -> None:
        self.repository = repository
        self.studio = studio
        self.provider = provider
        self.settings = settings
        self.artifacts = artifacts
        self.image_input_available = image_input_available
        self.image_generation_available = image_generation_available
        self.tool_registry = tool_registry or builtin_tool_registry(
            image_timeout_seconds=settings.agent_image_tool_timeout_seconds
        )
        self.tools_enabled = settings.agent_tools_enabled and (
            True if tools_available is None else tools_available
        )
        self._conditions: dict[str, asyncio.Condition] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._owner_locks: dict[str, asyncio.Lock] = {}
        self._user_cancelled: set[str] = set()
        self._approval_tasks: dict[str, asyncio.Task[None]] = {}
        self._lease_lost: set[str] = set()
        self._budget_timed_out: set[str] = set()
        self.executor_id = f"agent-executor-{uuid4().hex}"
        self._shutting_down = False

    async def create_run(
        self,
        owner_id: str,
        payload: AgentRunCreate,
        idempotency_key: str,
    ) -> AgentRunResponse:
        if not self.settings.agent_enabled or self.provider is None:
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
            executor_id=self.executor_id,
            execution_lease_expires_at=self._lease_expiry(),
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
            tool_calls = await self.repository.list_tool_calls(owner_id, run_id)
            for tool_call in tool_calls:
                if tool_call.response.status is AgentToolCallStatus.APPROVED:
                    await self.repository.finish_tool(
                        owner_id,
                        tool_call.response.id,
                        status=AgentToolCallStatus.FAILED,
                        result={
                            "ok": False,
                            "error": {"code": "AGENT_TOOL_CANCELLED"},
                        },
                        error_code="AGENT_TOOL_CANCELLED",
                        error_message="The Agent tool was cancelled before execution.",
                    )
            if not any(call.response.status is AgentToolCallStatus.RUNNING for call in tool_calls):
                await self._mark_cancelled(owner_id, run_id)
        return (await self.repository.get_run(owner_id, run_id)).response

    async def approve_tool_call(
        self,
        owner_id: str,
        tool_call_id: str,
        decision: AgentApprovalDecision,
    ) -> AgentToolDecisionResponse:
        return await self._decide_tool_call(owner_id, tool_call_id, decision, approve=True)

    async def reject_tool_call(
        self,
        owner_id: str,
        tool_call_id: str,
        decision: AgentApprovalDecision,
    ) -> AgentToolDecisionResponse:
        return await self._decide_tool_call(owner_id, tool_call_id, decision, approve=False)

    async def _decide_tool_call(
        self,
        owner_id: str,
        tool_call_id: str,
        decision: AgentApprovalDecision,
        *,
        approve: bool,
    ) -> AgentToolDecisionResponse:
        await self.repository.get_approval_by_tool_call(owner_id, tool_call_id)
        if approve and (not self.tools_enabled or self.provider is None):
            raise AgentRuntimeError(
                "AGENT_TOOLS_DISABLED",
                503,
                "Agent tool execution is disabled.",
            )
        try:
            result = await self.repository.decide_approval(
                owner_id,
                tool_call_id,
                approve=approve,
                decision_metadata=decision.model_dump(
                    mode="json", by_alias=True, exclude_none=True
                ),
                executor_id=self.executor_id,
                lease_expires_at=self._lease_expiry(),
            )
        except AgentStateConflict as exc:
            if (
                exc.latest.response.status.is_terminal
                or exc.latest.response.status is AgentRunStatus.CANCELLING
            ):
                result = await self.repository.expire_approval(owner_id, tool_call_id)
            else:
                raise AgentRuntimeError(
                    "AGENT_STATE_CONFLICT",
                    409,
                    "The Agent run state changed concurrently.",
                ) from exc
        expiry_task = self._approval_tasks.pop(tool_call_id, None)
        if expiry_task is not None:
            expiry_task.cancel()
        if result.claimed:
            self._start_tool_resume(result)
        await self._notify(result.run.response.id)
        return AgentToolDecisionResponse(
            toolCall=result.tool_call.response,
            approval=result.approval.response,
            run=result.run.response,
        )

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
        pending_by_run: dict[str, StoredAgentApproval] = {}
        for approval in await self.repository.list_pending_approvals():
            if approval.response.expires_at <= utc_now():
                result = await self.repository.expire_approval(
                    approval.owner_id, approval.response.tool_call_id
                )
                await self._notify(result.run.response.id)
            else:
                pending_by_run[approval.response.run_id] = approval
                self._schedule_approval_expiry(approval)
        for stored in await self.repository.list_recoverable_runs(utc_now()):
            if (
                stored.response.status is AgentRunStatus.WAITING_APPROVAL
                and stored.response.id in pending_by_run
            ):
                recovered.append(stored.response.id)
                continue
            try:
                stored = await self.repository.claim_run_execution(
                    stored.owner_id,
                    stored.response.id,
                    self.executor_id,
                    self._lease_expiry(),
                )
            except AgentExecutionOwned:
                continue
            renewal = asyncio.create_task(
                self._renew_recovery_lease(stored.owner_id, stored.response.id),
                name=f"agent-recovery-lease-{stored.response.id}",
            )
            try:
                for tool_call in await self.repository.list_tool_calls(
                    stored.owner_id, stored.response.id
                ):
                    if tool_call.response.status in {
                        AgentToolCallStatus.APPROVED,
                        AgentToolCallStatus.RUNNING,
                    }:
                        result = await self._tool_interruption_result(
                            stored.owner_id,
                            tool_call,
                            "AGENT_TOOL_RECOVERY_REQUIRED",
                        )
                        await self.repository.finish_tool(
                            stored.owner_id,
                            tool_call.response.id,
                            status=AgentToolCallStatus.FAILED,
                            result=result,
                            error_code="AGENT_TOOL_RECOVERY_REQUIRED",
                            error_message=(
                                "The interrupted tool was not replayed because its outcome is "
                                "unknown."
                            ),
                            executor_id=self.executor_id,
                        )
                if stored.response.status is AgentRunStatus.CANCELLING:
                    await self._mark_cancelled(
                        stored.owner_id,
                        stored.response.id,
                        executor_id=self.executor_id,
                    )
                else:
                    await self._mark_failed(
                        stored,
                        "AGENT_RECOVERY_REQUIRED",
                        "The interrupted run was terminated safely; create a new run to retry.",
                        self.executor_id,
                    )
                recovered.append(stored.response.id)
            except AgentExecutionOwned:
                continue
            finally:
                renewal.cancel()
                await asyncio.gather(renewal, return_exceptions=True)
                await self.repository.release_run_execution(
                    stored.owner_id, stored.response.id, self.executor_id
                )
        return recovered

    async def close(self) -> None:
        self._shutting_down = True
        approval_tasks = list(self._approval_tasks.values())
        for task in approval_tasks:
            task.cancel()
        if approval_tasks:
            await asyncio.gather(*approval_tasks, return_exceptions=True)
        self._approval_tasks.clear()
        tasks = list(self._tasks.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        if self.provider is not None:
            await self.provider.close()

    async def _consume_provider_events(self, owner_id: str, run_id: str, count: int) -> None:
        for _ in range(count):
            try:
                await self.repository.consume_provider_event(
                    owner_id,
                    run_id,
                    self.executor_id,
                    self.settings.agent_max_events_per_run,
                )
            except ValueError:
                raise AgentRuntimeError(
                    "AGENT_OUTPUT_INVALID", 422, "Agent event limit exceeded."
                ) from None

    async def _ensure_execution_owned(self, owner_id: str, run_id: str) -> None:
        await self.repository.renew_run_execution(
            owner_id,
            run_id,
            self.executor_id,
            self._lease_expiry(),
        )

    def _lease_expiry(self) -> datetime:
        return utc_now() + timedelta(seconds=self.settings.agent_execution_lease_seconds)

    def _start_lease_renewal(
        self, owner_id: str, run_id: str, execution_task: asyncio.Task[None]
    ) -> asyncio.Task[None]:
        return asyncio.create_task(
            self._renew_execution_lease(owner_id, run_id, execution_task),
            name=f"agent-lease-renewal-{run_id}",
        )

    async def _renew_recovery_lease(self, owner_id: str, run_id: str) -> None:
        try:
            while True:
                await asyncio.sleep(self.settings.agent_execution_lease_renew_seconds)
                await self.repository.renew_run_execution(
                    owner_id,
                    run_id,
                    self.executor_id,
                    self._lease_expiry(),
                )
        except (AgentExecutionOwned, asyncio.CancelledError, KeyError):
            return

    async def _renew_execution_lease(
        self, owner_id: str, run_id: str, execution_task: asyncio.Task[None]
    ) -> None:
        try:
            while True:
                await asyncio.sleep(self.settings.agent_execution_lease_renew_seconds)
                await self.repository.renew_run_execution(
                    owner_id,
                    run_id,
                    self.executor_id,
                    self._lease_expiry(),
                )
        except asyncio.CancelledError:
            raise
        except (AgentExecutionOwned, KeyError):
            self._lease_lost.add(run_id)
            execution_task.cancel()

    async def _release_execution_if_settled(self, owner_id: str, run_id: str) -> None:
        if run_id in self._lease_lost:
            self._lease_lost.discard(run_id)
            return
        latest = await self.repository.get_run(owner_id, run_id)
        if (
            latest.response.status.is_terminal
            or latest.response.status is AgentRunStatus.WAITING_APPROVAL
        ):
            await self.repository.release_run_execution(owner_id, run_id, self.executor_id)

    def _schedule_approval_expiry(self, approval: StoredAgentApproval) -> None:
        tool_call_id = approval.response.tool_call_id
        existing = self._approval_tasks.pop(tool_call_id, None)
        if existing is not None:
            existing.cancel()
        delay = max(0.0, (approval.response.expires_at - utc_now()).total_seconds())
        task = asyncio.create_task(
            self._expire_approval_later(approval.owner_id, tool_call_id, delay),
            name=f"agent-approval-expiry-{tool_call_id}",
        )
        self._approval_tasks[tool_call_id] = task
        task.add_done_callback(
            lambda completed, current_id=tool_call_id: self._forget_approval_task(
                current_id, completed
            )
        )

    def _forget_approval_task(self, tool_call_id: str, completed: asyncio.Task[None]) -> None:
        if self._approval_tasks.get(tool_call_id) is completed:
            self._approval_tasks.pop(tool_call_id, None)

    async def _expire_approval_later(self, owner_id: str, tool_call_id: str, delay: float) -> None:
        try:
            await asyncio.sleep(delay)
            result = await self.repository.expire_approval(owner_id, tool_call_id)
            await self._notify(result.run.response.id)
        except asyncio.CancelledError:
            raise
        except KeyError:
            return

    def _start(self, run: StoredAgentRun) -> None:
        task = asyncio.create_task(self._execute(run), name=f"agent-{run.response.id}")
        self._tasks[run.response.id] = task
        task.add_done_callback(
            lambda completed, run_id=run.response.id: self._forget_run_task(run_id, completed)
        )

    def _forget_run_task(self, run_id: str, completed: asyncio.Task[None]) -> None:
        if self._tasks.get(run_id) is completed:
            self._tasks.pop(run_id, None)

    def _start_tool_resume(self, decision: AgentToolDecision) -> None:
        run_id = decision.run.response.id
        existing = self._tasks.get(run_id)
        if existing is not None and not existing.done():
            existing.add_done_callback(lambda _completed: self._launch_tool_resume(decision))
            return
        self._launch_tool_resume(decision)

    def _launch_tool_resume(self, decision: AgentToolDecision) -> None:
        if self._shutting_down:
            return
        run_id = decision.run.response.id
        task = asyncio.create_task(
            self._resume_tool(decision), name=f"agent-tool-{decision.tool_call.response.id}"
        )
        self._tasks[run_id] = task
        task.add_done_callback(
            lambda completed, current_run_id=run_id: self._forget_run_task(
                current_run_id, completed
            )
        )

    async def _resume_tool(self, decision: AgentToolDecision) -> None:
        run_id = decision.run.response.id
        latest = await self.repository.get_run(decision.run.owner_id, run_id)
        remaining = max(
            0.0,
            self.settings.agent_max_run_seconds - latest.active_duration_seconds,
        )
        segment_started = asyncio.get_running_loop().time()
        work = asyncio.create_task(
            self._resume_tool_work(decision),
            name=f"agent-tool-work-{decision.tool_call.response.id}",
        )
        try:
            done, _ = await asyncio.wait({work}, timeout=remaining)
            if not done:
                self._budget_timed_out.add(run_id)
                work.cancel()
                await asyncio.gather(work, return_exceptions=True)
            else:
                await work
        except asyncio.CancelledError:
            work.cancel()
            await asyncio.gather(work, return_exceptions=True)
            raise
        finally:
            elapsed = asyncio.get_running_loop().time() - segment_started
            await self._await_cleanup(
                self._finalize_resume_segment(
                    decision.run.owner_id,
                    run_id,
                    elapsed,
                )
            )

    async def _resume_tool_work(self, decision: AgentToolDecision) -> None:
        try:
            decision.run = await self.repository.renew_run_execution(
                decision.run.owner_id,
                decision.run.response.id,
                self.executor_id,
                self._lease_expiry(),
            )
        except (AgentExecutionOwned, KeyError):
            return
        current_task = asyncio.current_task()
        assert current_task is not None
        renewal = self._start_lease_renewal(
            decision.run.owner_id, decision.run.response.id, current_task
        )
        try:
            if decision.approved:
                try:
                    decision.tool_call = await self.repository.start_tool(
                        decision.run.owner_id,
                        decision.tool_call.response.id,
                        frozenset({AgentRunStatus.EXECUTING_TOOL}),
                        frozenset({AgentToolCallStatus.APPROVED}),
                        self.executor_id,
                    )
                except AgentStateConflict as exc:
                    await self.repository.finish_tool(
                        decision.run.owner_id,
                        decision.tool_call.response.id,
                        status=AgentToolCallStatus.FAILED,
                        result={
                            "ok": False,
                            "error": {"code": "AGENT_TOOL_CANCELLED"},
                        },
                        error_code="AGENT_TOOL_CANCELLED",
                        error_message="The Agent tool was cancelled before execution.",
                        executor_id=self.executor_id,
                    )
                    if exc.latest.response.status is AgentRunStatus.CANCELLING:
                        await self._mark_cancelled(
                            decision.run.owner_id,
                            decision.run.response.id,
                            executor_id=self.executor_id,
                        )
                        return
                    raise
                await self._execute_tool_call(decision.run, decision.tool_call)
            latest = await self.repository.get_run(decision.run.owner_id, decision.run.response.id)
            await self._execute(latest, manage_lease=False, manage_budget=False)
        except asyncio.CancelledError:
            if decision.run.response.id in self._lease_lost:
                return
            if decision.run.response.id in self._budget_timed_out:
                current_call = await self.repository.get_tool_call(
                    decision.run.owner_id, decision.tool_call.response.id
                )
                if current_call.response.status in {
                    AgentToolCallStatus.APPROVED,
                    AgentToolCallStatus.RUNNING,
                }:
                    interruption_result = await asyncio.shield(
                        self._tool_interruption_result(
                            decision.run.owner_id,
                            current_call,
                            "AGENT_RUN_TIMEOUT",
                        )
                    )
                    await asyncio.shield(
                        self.repository.finish_tool(
                            decision.run.owner_id,
                            current_call.response.id,
                            status=AgentToolCallStatus.FAILED,
                            result=interruption_result,
                            error_code="AGENT_RUN_TIMEOUT",
                            error_message="The Agent run exhausted its active-time budget.",
                            executor_id=self.executor_id,
                        )
                    )
                await asyncio.shield(
                    self._mark_failed(
                        decision.run,
                        "AGENT_RUN_TIMEOUT",
                        "The Agent run exhausted its active-time budget.",
                        self.executor_id,
                    )
                )
                return
            if self._shutting_down and decision.run.response.id not in self._user_cancelled:
                interruption_result = await asyncio.shield(
                    self._tool_interruption_result(
                        decision.run.owner_id,
                        decision.tool_call,
                        "AGENT_TOOL_RECOVERY_REQUIRED",
                    )
                )
                await asyncio.shield(
                    self.repository.finish_tool(
                        decision.run.owner_id,
                        decision.tool_call.response.id,
                        status=AgentToolCallStatus.FAILED,
                        result=interruption_result,
                        error_code="AGENT_TOOL_RECOVERY_REQUIRED",
                        error_message=(
                            "The interrupted tool was not replayed because its outcome is unknown."
                        ),
                        executor_id=self.executor_id,
                    )
                )
                await asyncio.shield(
                    self._mark_failed(
                        decision.run,
                        "AGENT_STREAM_INTERRUPTED",
                        "The Gateway stopped before the approved tool completed.",
                        self.executor_id,
                    )
                )
            else:
                interruption_result = await asyncio.shield(
                    self._tool_interruption_result(
                        decision.run.owner_id,
                        decision.tool_call,
                        "AGENT_TOOL_CANCELLED",
                    )
                )
                await asyncio.shield(
                    self.repository.finish_tool(
                        decision.run.owner_id,
                        decision.tool_call.response.id,
                        status=AgentToolCallStatus.FAILED,
                        result=interruption_result,
                        error_code="AGENT_TOOL_CANCELLED",
                        error_message="The Agent tool was cancelled by the user.",
                        executor_id=self.executor_id,
                    )
                )
                await asyncio.shield(
                    self._mark_cancelled(
                        decision.run.owner_id,
                        decision.run.response.id,
                        executor_id=self.executor_id,
                    )
                )
            raise
        except AgentExecutionOwned:
            return
        except Exception:
            await self._mark_failed(
                decision.run,
                "AGENT_TOOL_FAILED",
                "The approved Agent tool failed safely.",
                self.executor_id,
            )
        finally:
            renewal.cancel()
            await asyncio.gather(renewal, return_exceptions=True)

    async def _execute(
        self,
        run: StoredAgentRun,
        *,
        manage_lease: bool = True,
        manage_budget: bool = True,
    ) -> None:
        if manage_lease:
            try:
                run = await self.repository.renew_run_execution(
                    run.owner_id,
                    run.response.id,
                    self.executor_id,
                    self._lease_expiry(),
                )
            except (AgentExecutionOwned, KeyError):
                return
        segment_started = asyncio.get_running_loop().time()
        remaining = (
            max(
                0.0,
                self.settings.agent_max_run_seconds - run.active_duration_seconds,
            )
            if manage_budget
            else None
        )
        current_task = asyncio.current_task()
        assert current_task is not None
        renewal = (
            self._start_lease_renewal(run.owner_id, run.response.id, current_task)
            if manage_lease
            else None
        )
        try:
            async with asyncio.timeout(remaining):
                await self._run_loop(run)
        except asyncio.CancelledError:
            if run.response.id in self._lease_lost:
                return
            latest = await self.repository.get_run(run.owner_id, run.response.id)
            if latest.response.status is AgentRunStatus.WAITING_APPROVAL:
                return
            if self._shutting_down and run.response.id not in self._user_cancelled:
                await asyncio.shield(
                    self._finish_unstarted_tools(
                        run.owner_id,
                        run.response.id,
                        "AGENT_TOOL_RECOVERY_REQUIRED",
                        "The interrupted tool was not replayed because its outcome is unknown.",
                    )
                )
                await asyncio.shield(
                    self._mark_failed(
                        run,
                        "AGENT_STREAM_INTERRUPTED",
                        "The Gateway stopped before the run completed.",
                        self.executor_id,
                    )
                )
            else:
                await asyncio.shield(
                    self._finish_unstarted_tools(
                        run.owner_id,
                        run.response.id,
                        "AGENT_TOOL_CANCELLED",
                        "The Agent tool was cancelled before execution.",
                    )
                )
                await asyncio.shield(
                    self._mark_cancelled(
                        run.owner_id, run.response.id, executor_id=self.executor_id
                    )
                )
            raise
        except TimeoutError:
            await self._mark_failed(
                run,
                "AGENT_RUN_TIMEOUT",
                "The Agent run timed out safely.",
                self.executor_id,
            )
        except AgentExecutionOwned:
            return
        except AgentStateConflict as exc:
            if exc.latest.response.status.is_terminal:
                return
            if exc.latest.response.status is AgentRunStatus.CANCELLING:
                await self._mark_cancelled(
                    run.owner_id, run.response.id, executor_id=self.executor_id
                )
                return
            await self._mark_failed(
                run,
                "AGENT_STATE_CONFLICT",
                "The Agent run state changed concurrently.",
                self.executor_id,
            )
        except AgentProviderError as exc:
            await self._mark_failed(
                run, exc.code.value, _provider_message(exc.code), self.executor_id
            )
        except AgentRuntimeError as exc:
            await self._mark_failed(run, exc.code, exc.message, self.executor_id)
        except Exception:
            await self._mark_failed(
                run,
                "AGENT_PROVIDER_UNAVAILABLE",
                "The Agent run failed safely.",
                self.executor_id,
            )
        finally:
            elapsed = asyncio.get_running_loop().time() - segment_started
            await self._await_cleanup(
                self._finalize_execute_segment(
                    run.owner_id,
                    run.response.id,
                    elapsed,
                    renewal,
                    manage_budget=manage_budget,
                )
            )

    async def _await_cleanup(self, cleanup: Awaitable[None]) -> None:
        task = asyncio.create_task(cleanup)
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            await task
            raise

    async def _finalize_resume_segment(self, owner_id: str, run_id: str, elapsed: float) -> None:
        with suppress(AgentExecutionOwned, KeyError):
            await self.repository.record_active_seconds(
                owner_id,
                run_id,
                self.executor_id,
                elapsed,
            )
        await self.repository.release_run_execution(owner_id, run_id, self.executor_id)
        self._budget_timed_out.discard(run_id)

    async def _finalize_execute_segment(
        self,
        owner_id: str,
        run_id: str,
        elapsed: float,
        renewal: asyncio.Task[None] | None,
        *,
        manage_budget: bool,
    ) -> None:
        if manage_budget:
            with suppress(AgentExecutionOwned, KeyError):
                await self.repository.record_active_seconds(
                    owner_id,
                    run_id,
                    self.executor_id,
                    elapsed,
                )
        if renewal is not None:
            renewal.cancel()
            await asyncio.gather(renewal, return_exceptions=True)
            await self._release_execution_if_settled(owner_id, run_id)

    async def _tool_interruption_result(
        self,
        owner_id: str,
        tool_call: StoredAgentToolCall,
        error_code: str,
    ) -> dict[str, object]:
        result: dict[str, object] = {
            "ok": False,
            "error": {"code": error_code},
        }
        if self.artifacts is None or tool_call.response.tool_name != "generate_reference_image":
            return result
        await self.artifacts.cleanup_unregistered_generated_images(owner_id, tool_call.response.id)
        recovered_assets = await self.artifacts.list_generated_images(
            owner_id, tool_call.response.id
        )
        if recovered_assets:
            result["assets"] = [_asset_tool_snapshot(asset) for asset in recovered_assets]
            result["partial"] = True
        return result

    async def _provider_image_inputs(self, run: StoredAgentRun) -> list[str]:
        if not self.image_input_available or self.artifacts is None:
            return []
        image_asset_ids = {
            item.get("id")
            for item in run.response.input_snapshot.get("assetMetadata", [])
            if isinstance(item, dict) and item.get("type") == "image"
        }
        image_inputs: list[str] = []
        for asset_id in run.response.input_snapshot.get("assetIds", []):
            if not isinstance(asset_id, str) or asset_id not in image_asset_ids:
                continue
            try:
                image_inputs.append(
                    await self.artifacts.provider_image_data_url(
                        run.owner_id,
                        asset_id,
                        max_bytes=self.settings.agent_max_image_bytes,
                    )
                )
            except KeyError:
                continue
            except ValueError as exc:
                raise AgentRuntimeError(
                    "AGENT_IMAGE_INVALID",
                    422,
                    "An input image could not be validated safely.",
                ) from exc
        return image_inputs

    async def _finish_unstarted_tools(
        self, owner_id: str, run_id: str, error_code: str, error_message: str
    ) -> None:
        for tool_call in await self.repository.list_tool_calls(owner_id, run_id):
            if tool_call.response.status is AgentToolCallStatus.APPROVED:
                await self.repository.finish_tool(
                    owner_id,
                    tool_call.response.id,
                    status=AgentToolCallStatus.FAILED,
                    result={"ok": False, "error": {"code": error_code}},
                    error_code=error_code,
                    error_message=error_message,
                    executor_id=self.executor_id,
                )

    async def _run_loop(self, run: StoredAgentRun) -> None:
        assert self.provider is not None
        run = await self.repository.get_run(run.owner_id, run.response.id)
        if (
            run.response.status.is_terminal
            or run.response.status is AgentRunStatus.WAITING_APPROVAL
        ):
            return
        if run.response.status is not AgentRunStatus.STREAMING:
            previous_status = run.response.status
            run.response = self._with_status(
                run.response,
                AgentRunStatus.STREAMING,
                started_at=run.response.started_at or utc_now(),
            )
            await self.repository.transition_run(
                run,
                "agent.run.started"
                if previous_status is AgentRunStatus.QUEUED
                else "agent.run.resumed",
                {"status": AgentRunStatus.STREAMING.value},
                frozenset({previous_status}),
                self.executor_id,
            )
            await self._notify(run.response.id)
        usage = run.response.usage
        while usage.provider_requests < self.settings.agent_max_turns:
            current = await self.repository.get_run(run.owner_id, run.response.id)
            if current.response.status is not AgentRunStatus.STREAMING:
                if (
                    current.response.status.is_terminal
                    or current.response.status is AgentRunStatus.WAITING_APPROVAL
                ):
                    return
                raise AgentStateConflict(current)
            run = current
            tool_calls = await self.repository.list_tool_calls(run.owner_id, run.response.id)
            if len(tool_calls) > self.settings.agent_max_tool_calls:
                raise AgentRuntimeError(
                    "AGENT_TOOL_BUDGET_EXCEEDED", 422, "Agent tool-call budget exceeded."
                )
            messages = await self.repository.list_messages(
                run.owner_id, run.response.thread_id, limit=20
            )
            next_request_count = usage.provider_requests + 1
            image_inputs = await self._provider_image_inputs(run)
            request = ProviderRequest(
                model=run.response.model,
                instructions=SYSTEM_INSTRUCTIONS,
                input_items=_provider_input(
                    messages,
                    run.response.input_snapshot,
                    tool_calls,
                    image_inputs,
                ),
                tools=(
                    self.tool_registry.provider_tools(
                        image_generation_available=self.image_generation_available
                    )
                    if self.tools_enabled
                    else []
                ),
                reasoning_effort=self.settings.agent_reasoning_effort,
                max_output_tokens=self.settings.agent_max_output_tokens,
                request_id=f"{run.response.id}-turn-{next_request_count}",
            )
            text_parts: list[str] = []
            text_length = 0
            provider_failed: str | None = None
            response_completed = False
            proposals: list[ProviderEvent] = []
            turn_usage = AgentUsage(providerRequests=1)
            async for event in self.provider.stream_response(request):
                try:
                    run = await self.repository.consume_provider_event(
                        run.owner_id,
                        run.response.id,
                        self.executor_id,
                        self.settings.agent_max_events_per_run,
                    )
                except ValueError:
                    raise AgentRuntimeError(
                        "AGENT_OUTPUT_INVALID", 422, "Agent event limit exceeded."
                    ) from None
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
                            "AGENT_OUTPUT_INVALID",
                            422,
                            "Agent output exceeded the allowed size.",
                        )
                    text_parts.append(delta)
                    text_length += len(delta)
                    await self.repository.append_event(
                        run.owner_id,
                        run.response.id,
                        "agent.message.delta",
                        {"delta": delta},
                        frozenset({AgentRunStatus.STREAMING}),
                        self.executor_id,
                    )
                    await self._notify(run.response.id)
                elif event.event_type is ProviderEventType.TEXT_COMPLETED and not text_parts:
                    text_parts.append(str(event.data.get("text", ""))[:20_000])
                elif event.event_type is ProviderEventType.USAGE_COMPLETED:
                    turn_usage = AgentUsage(
                        inputTokens=int(event.data.get("inputTokens", 0)),
                        outputTokens=int(event.data.get("outputTokens", 0)),
                        totalTokens=int(event.data.get("totalTokens", 0)),
                        providerRequests=1,
                    )
                elif event.event_type is ProviderEventType.TOOL_PROPOSED:
                    proposals.append(event)
                elif event.event_type is ProviderEventType.RESPONSE_FAILED:
                    provider_failed = str(
                        event.data.get("code", ProviderErrorCode.PROVIDER_UNAVAILABLE.value)
                    )
                elif event.event_type is ProviderEventType.RESPONSE_COMPLETED:
                    response_completed = True
            usage = _add_usage(usage, turn_usage)
            run.response = run.response.model_copy(update={"usage": usage})
            if provider_failed:
                raise AgentRuntimeError(provider_failed, 503, "The Agent provider failed.")
            if not response_completed:
                raise AgentRuntimeError(
                    "AGENT_STREAM_INTERRUPTED", 503, "The Agent stream ended unexpectedly."
                )
            if proposals:
                for proposal in proposals:
                    if await self._process_tool_proposal(run, proposal):
                        return
                continue
            try:
                content = AgentMessageContent.model_validate_json("".join(text_parts))
            except ValidationError:
                raise AgentRuntimeError(
                    "AGENT_OUTPUT_INVALID",
                    422,
                    "The Agent returned an invalid structured response.",
                ) from None
            content = await self._content_with_tool_proposal(run, content)
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
                    self.executor_id,
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
                self.executor_id,
            )
            run.response = run.response.model_copy(update={"output_message_id": message.id})
            await self._notify(run.response.id)
            return
        raise AgentRuntimeError(
            "AGENT_TURN_BUDGET_EXCEEDED", 422, "Agent model-turn budget exceeded."
        )

    async def _process_tool_proposal(self, run: StoredAgentRun, event: ProviderEvent) -> bool:
        if not self.tools_enabled:
            raise AgentRuntimeError("AGENT_TOOL_NOT_ALLOWED", 422, "Agent tools are disabled.")
        call_id = event.data.get("callId")
        name = event.data.get("name")
        arguments = event.data.get("arguments")
        if (
            not isinstance(call_id, str)
            or not isinstance(name, str)
            or not isinstance(arguments, dict)
        ):
            raise AgentRuntimeError(
                "AGENT_TOOL_ARGUMENTS_INVALID", 422, "Agent tool arguments are invalid."
            )
        try:
            definition = self.tool_registry.require(name)
        except ValueError:
            raise AgentRuntimeError(
                "AGENT_TOOL_NOT_ALLOWED", 422, "The proposed Agent tool is not allowed."
            ) from None
        if definition.requires_image_generation and not self.image_generation_available:
            raise AgentRuntimeError(
                "AGENT_IMAGE_NOT_SUPPORTED",
                503,
                "Agent image generation is unavailable.",
            )
        try:
            validated = self.tool_registry.validate_arguments(name, arguments)
        except ValidationError:
            raise AgentRuntimeError(
                "AGENT_TOOL_ARGUMENTS_INVALID",
                422,
                "The proposed Agent tool arguments are invalid.",
            ) from None
        normalized = validated.model_dump(mode="json", by_alias=True, exclude_none=True)
        try:
            normalized, _, arguments_hash = canonical_arguments(normalized)
        except ValueError:
            raise AgentRuntimeError(
                "AGENT_TOOL_ARGUMENTS_INVALID",
                422,
                "The proposed Agent tool arguments are too large.",
            ) from None
        existing_calls = await self.repository.list_tool_calls(run.owner_id, run.response.id)
        duplicate = next(
            (call for call in existing_calls if call.provider_call_id == call_id), None
        )
        if duplicate is None:
            if len(existing_calls) >= self.settings.agent_max_tool_calls:
                raise AgentRuntimeError(
                    "AGENT_TOOL_BUDGET_EXCEEDED", 422, "Agent tool-call budget exceeded."
                )
            if (
                sum(call.response.tool_name == name for call in existing_calls)
                >= definition.max_calls_per_run
            ):
                raise AgentRuntimeError(
                    "AGENT_TOOL_BUDGET_EXCEEDED",
                    422,
                    "Agent per-tool budget exceeded.",
                )
        approval: StoredAgentApproval | None = None
        status = AgentToolCallStatus.PROPOSED
        if definition.requires_approval:
            approvals = [
                call
                for call in existing_calls
                if call.response.status is AgentToolCallStatus.WAITING_APPROVAL
                or call.response.risk.value in {"write", "costly", "destructive"}
            ]
            if len(approvals) >= self.settings.agent_max_approvals:
                raise AgentRuntimeError(
                    "AGENT_APPROVAL_BUDGET_EXCEEDED",
                    422,
                    "Agent approval budget exceeded.",
                )
            status = AgentToolCallStatus.WAITING_APPROVAL
        now = utc_now()
        tool_call = StoredAgentToolCall(
            owner_id=run.owner_id,
            provider_call_id=call_id,
            response=AgentToolCallResponse(
                id=f"agent-tool-{uuid4().hex[:20]}",
                runId=run.response.id,
                toolName=name,
                toolVersion=definition.version,
                risk=definition.risk,
                arguments=normalized,
                argumentsHash=arguments_hash,
                status=status,
                createdAt=now,
            ),
        )
        if definition.requires_approval:
            approval = StoredAgentApproval(
                owner_id=run.owner_id,
                response=AgentApprovalResponse(
                    id=f"agent-approval-{uuid4().hex[:20]}",
                    runId=run.response.id,
                    toolCallId=tool_call.response.id,
                    argumentsHash=arguments_hash,
                    status=AgentApprovalStatus.PENDING,
                    estimatedCost=definition.estimated_cost,
                    expiresAt=now + timedelta(seconds=self.settings.agent_approval_ttl_seconds),
                ),
                decision_metadata={},
            )
        stored_call, stored_approval, created = await self.repository.propose_tool_call(
            run, tool_call, approval, self.executor_id
        )
        await self._notify(run.response.id)
        if stored_approval is not None:
            if (
                stored_approval.response.status is AgentApprovalStatus.PENDING
                and stored_call.response.status is AgentToolCallStatus.WAITING_APPROVAL
            ):
                self._schedule_approval_expiry(stored_approval)
                return True
            if stored_call.response.status in {
                AgentToolCallStatus.SUCCEEDED,
                AgentToolCallStatus.FAILED,
                AgentToolCallStatus.REJECTED,
                AgentToolCallStatus.EXPIRED,
            }:
                return False
            raise AgentRuntimeError(
                "AGENT_RECOVERY_REQUIRED",
                409,
                "The approved Agent tool cannot be replayed safely.",
            )
        if not created:
            if stored_call.response.status in {
                AgentToolCallStatus.SUCCEEDED,
                AgentToolCallStatus.FAILED,
                AgentToolCallStatus.REJECTED,
                AgentToolCallStatus.EXPIRED,
            }:
                return False
            raise AgentRuntimeError(
                "AGENT_RECOVERY_REQUIRED",
                409,
                "The Agent tool state cannot be replayed safely.",
            )
        stored_call = await self.repository.start_tool(
            run.owner_id,
            stored_call.response.id,
            frozenset({AgentRunStatus.STREAMING}),
            frozenset({AgentToolCallStatus.PROPOSED}),
            self.executor_id,
        )
        await self._execute_tool_call(run, stored_call)
        return False

    async def _execute_tool_call(
        self, run: StoredAgentRun, tool_call: StoredAgentToolCall
    ) -> StoredAgentToolCall:
        try:
            result = await self.tool_registry.execute(
                tool_call.response.tool_name,
                ToolExecutionContext(
                    run.owner_id,
                    run,
                    self.studio,
                    tool_call_id=tool_call.response.id,
                    provider=self.provider,
                    artifacts=self.artifacts,
                    image_model=self.settings.agent_image_model or run.response.model,
                    max_image_bytes=self.settings.agent_max_image_bytes,
                    image_input_available=self.image_input_available,
                    ensure_execution_owned=partial(
                        self._ensure_execution_owned,
                        run.owner_id,
                        run.response.id,
                    ),
                    consume_provider_events=partial(
                        self._consume_provider_events,
                        run.owner_id,
                        run.response.id,
                    ),
                ),
                tool_call.response.arguments,
            )
        except AgentExecutionOwned:
            raise
        except AgentProviderError as exc:
            stored = await self.repository.finish_tool(
                run.owner_id,
                tool_call.response.id,
                status=AgentToolCallStatus.FAILED,
                result={"ok": False, "error": {"code": exc.code.value}},
                error_code=exc.code.value,
                error_message=_provider_message(exc.code),
                executor_id=self.executor_id,
            )
        except KeyError:
            stored = await self.repository.finish_tool(
                run.owner_id,
                tool_call.response.id,
                status=AgentToolCallStatus.FAILED,
                result={"ok": False, "error": {"code": "AGENT_RESOURCE_NOT_FOUND"}},
                error_code="AGENT_RESOURCE_NOT_FOUND",
                error_message="The requested resource was not found.",
                executor_id=self.executor_id,
            )
        except RuntimeError as exc:
            error_code = str(exc)
            if not error_code.startswith("AGENT_") or len(error_code) > 100:
                error_code = "AGENT_TOOL_FAILED"
            stored = await self.repository.finish_tool(
                run.owner_id,
                tool_call.response.id,
                status=AgentToolCallStatus.FAILED,
                result={"ok": False, "error": {"code": error_code}},
                error_code=error_code,
                error_message="The Agent tool failed safely.",
                executor_id=self.executor_id,
            )
        except (ValidationError, ValueError):
            stored = await self.repository.finish_tool(
                run.owner_id,
                tool_call.response.id,
                status=AgentToolCallStatus.FAILED,
                result={"ok": False, "error": {"code": "AGENT_TOOL_FAILED"}},
                error_code="AGENT_TOOL_FAILED",
                error_message="The Agent tool failed safely.",
                executor_id=self.executor_id,
            )
        else:
            stored = await self.repository.finish_tool(
                run.owner_id,
                tool_call.response.id,
                status=AgentToolCallStatus.SUCCEEDED,
                result=result,
                executor_id=self.executor_id,
            )
        await self._notify(run.response.id)
        return stored

    async def _content_with_tool_proposal(
        self, run: StoredAgentRun, content: AgentMessageContent
    ) -> AgentMessageContent:
        if content.draft_proposal is not None:
            return content
        for tool_call in reversed(
            await self.repository.list_tool_calls(run.owner_id, run.response.id)
        ):
            if (
                tool_call.response.tool_name == "propose_draft_patch"
                and tool_call.response.status is AgentToolCallStatus.SUCCEEDED
                and tool_call.response.result is not None
            ):
                result = tool_call.response.result
                try:
                    return AgentMessageContent.model_validate(
                        {
                            "text": content.text,
                            "draftProposal": result.get("proposal"),
                            "rationale": content.rationale or result.get("rationale", []),
                            "warnings": content.warnings or result.get("warnings", []),
                        }
                    )
                except ValidationError:
                    break
        return content

    async def _mark_failed(
        self,
        run: StoredAgentRun,
        code: str,
        message: str,
        executor_id: str | None = None,
    ) -> None:
        for _ in range(3):
            latest = await self.repository.get_run(run.owner_id, run.response.id)
            if latest.response.status.is_terminal:
                return
            if latest.response.status is AgentRunStatus.CANCELLING:
                await self._mark_cancelled(run.owner_id, run.response.id, executor_id=executor_id)
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
                    executor_id,
                )
            except AgentExecutionOwned:
                return
            except AgentStateConflict as exc:
                if exc.latest.response.status.is_terminal:
                    return
                continue
            await self._notify(latest.response.id)
            return
        raise AgentRuntimeError(
            "AGENT_STATE_CONFLICT", 409, "The Agent run state changed concurrently."
        )

    async def _mark_cancelled(
        self, owner_id: str, run_id: str, *, executor_id: str | None = None
    ) -> None:
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
                    executor_id,
                )
            except AgentExecutionOwned:
                return
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


def _provider_input(
    messages,
    snapshot: dict[str, object],
    tool_calls: list[StoredAgentToolCall],
    image_inputs: list[str] | None = None,
) -> list[dict[str, object]]:
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
        content: list[dict[str, object]] = [
            {
                "type": (
                    "output_text" if message.role is AgentMessageRole.ASSISTANT else "input_text"
                ),
                "text": text,
            }
        ]
        if index == len(messages) - 1 and message.role is AgentMessageRole.USER:
            content.extend(
                {"type": "input_image", "image_url": image_url} for image_url in image_inputs or []
            )
        items.append(
            {
                "role": "assistant" if message.role is AgentMessageRole.ASSISTANT else "user",
                "content": content,
            }
        )
    for tool_call in tool_calls:
        response = tool_call.response
        items.append(
            {
                "type": "function_call",
                "call_id": tool_call.provider_call_id,
                "name": response.tool_name,
                "arguments": json.dumps(
                    response.arguments,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
            }
        )
        if response.status is AgentToolCallStatus.SUCCEEDED:
            output = response.result or {}
        elif response.status in {
            AgentToolCallStatus.FAILED,
            AgentToolCallStatus.REJECTED,
            AgentToolCallStatus.EXPIRED,
        }:
            output = response.result or {
                "ok": False,
                "error": {"code": response.error_code or "AGENT_TOOL_FAILED"},
            }
        else:
            continue
        items.append(
            {
                "type": "function_call_output",
                "call_id": tool_call.provider_call_id,
                "output": json.dumps(
                    output,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
            }
        )
    return items


def _asset_tool_snapshot(asset: AssetResponse) -> dict[str, object]:
    return {
        "id": asset.id,
        "type": asset.type,
        "title": asset.title[:200],
        "mediaType": asset.media_type,
        "sizeBytes": asset.size_bytes,
        "width": asset.width,
        "height": asset.height,
        "createdAt": asset.created_at.isoformat(),
    }


def _add_usage(current: AgentUsage, turn: AgentUsage) -> AgentUsage:
    return AgentUsage(
        inputTokens=current.input_tokens + turn.input_tokens,
        outputTokens=current.output_tokens + turn.output_tokens,
        totalTokens=current.total_tokens + turn.total_tokens,
        providerRequests=current.provider_requests + 1,
    )


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
