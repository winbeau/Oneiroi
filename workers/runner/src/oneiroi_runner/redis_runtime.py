import asyncio
import json
from collections.abc import Awaitable, Callable
from contextlib import suppress
from datetime import UTC, datetime
from typing import Any

from redis.asyncio import Redis
from redis.exceptions import ResponseError

from oneiroi_common.generation import InternalI2VRequest
from oneiroi_common.runner_protocol import (
    JOB_EVENT_STREAM_TEMPLATE,
    RUNNER_CONTROL_STREAM_TEMPLATE,
    SLOT_CONTROL_STREAM_TEMPLATE,
    SLOT_JOB_STREAM_TEMPLATE,
    RunnerCommand,
    RunnerCommandResult,
    RunnerCommandType,
    RunnerHeartbeat,
)
from oneiroi_runner.heartbeat import RedisHeartbeatPublisher, heartbeat_loop
from oneiroi_runner.settings import RunnerSettings
from oneiroi_runner.supervisor import ModelWorkerSupervisor
from oneiroi_runner.telemetry import NvmlTelemetryProvider


class RedisRunnerRuntime:
    def __init__(
        self,
        settings: RunnerSettings,
        supervisor: ModelWorkerSupervisor,
        *,
        heartbeat_factory: Callable[[], Awaitable[RunnerHeartbeat]] | None = None,
    ) -> None:
        self.settings = settings
        self.supervisor = supervisor
        self.client = Redis.from_url(settings.redis_url, decode_responses=True)
        self.heartbeat_publisher = RedisHeartbeatPublisher(settings.redis_url)
        self.group = f"oneiroi-runner:{settings.name}"
        self.consumer = settings.name
        self.current_slot_id: str | None = None
        self.current_session_id: str | None = None
        self.current_fencing_token: str | None = None
        self._slot_tasks: list[asyncio.Task[None]] = []
        self.heartbeat_factory = heartbeat_factory or self._heartbeat

    async def run(self, stop_event: asyncio.Event) -> None:
        bootstrap_stream = RUNNER_CONTROL_STREAM_TEMPLATE.format(gpu_id=self.settings.gpu_id)
        await self._ensure_group(bootstrap_stream)
        heartbeat_task = asyncio.create_task(
            heartbeat_loop(
                self.heartbeat_publisher,
                self.heartbeat_factory,
                interval_seconds=self.settings.heartbeat_seconds,
                stop_event=stop_event,
            ),
            name=f"heartbeat-{self.settings.name}",
        )
        try:
            while not stop_event.is_set():
                message = await self._read_group(bootstrap_stream)
                if message is None:
                    continue
                message_id, fields = message
                try:
                    command = RunnerCommand.model_validate_json(fields["command"])
                    await self._handle_bootstrap(command)
                finally:
                    await self.client.xack(bootstrap_stream, self.group, message_id)
        finally:
            heartbeat_task.cancel()
            with suppress(asyncio.CancelledError):
                await heartbeat_task
            await self._stop_slot_tasks()
            if self.supervisor.worker_pid is not None:
                await self.supervisor.release()
            await self.heartbeat_publisher.close()
            await self.client.aclose()

    async def _handle_bootstrap(self, command: RunnerCommand) -> None:
        if command.command_type is not RunnerCommandType.LOAD_PROFILE:
            await self._result(command, status="failed", error="INVALID_BOOTSTRAP_COMMAND")
            return
        if command.payload.get("gpuId") != self.settings.gpu_id:
            await self._result(command, status="failed", error="GPU_ID_MISMATCH")
            return
        if command.pipeline_spec is None:
            await self._result(command, status="failed", error="PIPELINE_SPEC_REQUIRED")
            return
        cached = await self._cached_result(command.command_id)
        if cached is not None:
            await self._publish_result(cached)
            return
        try:
            ready = await self.supervisor.load(command.pipeline_spec)
            self.current_slot_id = command.slot_id
            self.current_session_id = str(command.payload.get("sessionId") or "")
            self.current_fencing_token = str(command.payload.get("fencingToken") or "")
            await self._start_slot_tasks(command.slot_id)
            await self._result(
                command,
                status="succeeded",
                payload={
                    "workerPid": ready.worker_pid,
                    "loadSeconds": ready.load_seconds,
                    "adapterLoadCount": ready.adapter_load_count,
                    "reused": ready.reused,
                },
            )
        except Exception as exc:
            await self._result(command, status="failed", error=str(exc))

    async def _start_slot_tasks(self, slot_id: str) -> None:
        await self._stop_slot_tasks()
        control_stream = SLOT_CONTROL_STREAM_TEMPLATE.format(slot_id=slot_id)
        job_stream = SLOT_JOB_STREAM_TEMPLATE.format(slot_id=slot_id)
        await self._ensure_group(control_stream)
        await self._ensure_group(job_stream)
        self._slot_tasks = [
            asyncio.create_task(self._control_loop(control_stream), name=f"control-{slot_id}"),
            asyncio.create_task(self._job_loop(job_stream), name=f"jobs-{slot_id}"),
        ]

    async def _stop_slot_tasks(self) -> None:
        for task in self._slot_tasks:
            task.cancel()
        for task in self._slot_tasks:
            with suppress(asyncio.CancelledError):
                await task
        self._slot_tasks.clear()

    async def _control_loop(self, stream: str) -> None:
        while True:
            message = await self._read_group(stream)
            if message is None:
                continue
            message_id, fields = message
            try:
                command = RunnerCommand.model_validate_json(fields["command"])
                await self._handle_slot_command(command)
            finally:
                await self.client.xack(stream, self.group, message_id)

    async def _handle_slot_command(self, command: RunnerCommand) -> None:
        cached = await self._cached_result(command.command_id)
        if cached is not None:
            await self._publish_result(cached)
            return
        if not self._valid_fencing(command.payload):
            await self._result(command, status="failed", error="FENCING_TOKEN_MISMATCH")
            return
        try:
            if command.command_type is RunnerCommandType.CANCEL_JOB:
                if not command.job_id:
                    raise ValueError("JOB_ID_REQUIRED")
                self.supervisor.cancel_job(command.job_id)
                await self._result(command, status="succeeded")
                return
            if command.command_type is not RunnerCommandType.UNLOAD:
                raise ValueError("INVALID_SLOT_COMMAND")
            report = await self.supervisor.release()
            await self._result(
                command,
                status="succeeded" if report.succeeded else "failed",
                payload={
                    "childExited": report.child_exited,
                    "memoryReleased": report.memory_released,
                    "escalatedToTerminate": report.escalated_to_terminate,
                    "escalatedToKill": report.escalated_to_kill,
                },
                error=None if report.succeeded else "GPU_MEMORY_NOT_RELEASED",
            )
            if report.succeeded:
                self.current_slot_id = None
                self.current_session_id = None
                self.current_fencing_token = None
        except Exception as exc:
            await self._result(command, status="failed", error=str(exc))

    async def _job_loop(self, stream: str) -> None:
        while True:
            message = await self._read_group(stream)
            if message is None:
                continue
            message_id, fields = message
            job_id = fields.get("jobId", "")
            try:
                payload = json.loads(fields["payload"])
                if payload.get("fencingToken") != self.current_fencing_token:
                    raise RuntimeError("FENCING_TOKEN_MISMATCH")
                await self._run_job(job_id, payload)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                await self._publish_job_event(
                    job_id,
                    "failed",
                    {"error": type(exc).__name__, "message": str(exc)},
                )
            finally:
                await self.client.xack(stream, self.group, message_id)

    async def _run_job(self, job_id: str, payload: dict[str, Any]) -> None:
        request = self._generation_request(job_id, payload)
        pending_events: list[asyncio.Task[str]] = []

        def progress(message: dict[str, object]) -> None:
            pending_events.append(
                asyncio.create_task(self._publish_job_event(job_id, "progress", message))
            )

        try:
            result = await self.supervisor.run_job(
                request,
                progress,
                timeout_seconds=self.settings.job_timeout_seconds,
            )
            if pending_events:
                await asyncio.gather(*pending_events)
            await self._publish_job_event(
                job_id,
                "succeeded",
                {"result": result.model_dump(mode="json", by_alias=True)},
            )
        except asyncio.CancelledError:
            await self._publish_job_event(job_id, "cancelled", {"jobId": job_id})
            raise
        except Exception as exc:
            message = str(exc)
            code = message.split(":", 1)[0] or type(exc).__name__
            await self._publish_job_event(
                job_id,
                "failed",
                {"error": code, "message": message},
            )

    def _generation_request(self, job_id: str, payload: dict[str, Any]) -> InternalI2VRequest:
        job = payload["job"]
        draft = job["draft"]
        width, height = self._dimensions(draft["resolution"], draft["ratio"])
        frames = round((int(draft["duration"]) * 24 - 1) / 8) * 8 + 1
        inputs = payload.get("inputPaths") or [None, None]
        return InternalI2VRequest(
            jobId=job_id,
            prompt=draft["prompt"],
            negativePrompt=draft.get("negativePrompt", ""),
            profile=draft["profile"],
            width=width,
            height=height,
            numFrames=frames,
            frameRate=24,
            seed=draft.get("seed", 42),
            enhancePrompt=draft.get("enhancePrompt", False),
            firstFramePath=inputs[0],
            lastFramePath=inputs[1],
            firstFrameStrength=draft.get("firstStrength", 1),
            lastFrameStrength=draft.get("lastStrength", 1),
        )

    @staticmethod
    def _dimensions(resolution: str, ratio: str) -> tuple[int, int]:
        landscape = (1920, 1088) if resolution == "1080p" else (1280, 704)
        if ratio == "9:16":
            return landscape[1], landscape[0]
        if ratio == "1:1":
            return landscape[1], landscape[1]
        return landscape

    def _valid_fencing(self, payload: dict[str, Any]) -> bool:
        return (
            payload.get("gpuId") == self.settings.gpu_id
            and payload.get("sessionId") == self.current_session_id
            and payload.get("fencingToken") == self.current_fencing_token
        )

    async def _heartbeat(self) -> RunnerHeartbeat:
        samples = await asyncio.to_thread(NvmlTelemetryProvider().collect)
        sample = next(item for item in samples if item.uuid == self.settings.gpu_id)
        return RunnerHeartbeat(
            runnerId=self.settings.name,
            slotId=self.current_slot_id or f"unassigned-{self.settings.name}",
            gpuId=self.settings.gpu_id,
            physicalIndex=sample.physical_index,
            state=self.supervisor.state.value,
            vram_used_mib=sample.vram_used_mib,
            vram_total_mib=sample.vram_total_mib,
            workerPid=self.supervisor.worker_pid,
            occurredAt=datetime.now(UTC).isoformat(),
        )

    async def _ensure_group(self, stream: str) -> None:
        try:
            await self.client.xgroup_create(stream, self.group, id="0-0", mkstream=True)
        except ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    async def _read_group(self, stream: str) -> tuple[str, dict[str, str]] | None:
        pending = await self.client.xreadgroup(
            self.group,
            self.consumer,
            {stream: "0"},
            count=1,
        )
        if pending and pending[0][1]:
            return pending[0][1][0]
        messages = await self.client.xreadgroup(
            self.group,
            self.consumer,
            {stream: ">"},
            count=1,
            block=1_000,
        )
        if not messages:
            return None
        return messages[0][1][0]

    async def _cached_result(self, command_id: str) -> RunnerCommandResult | None:
        value = await self.client.get(f"oneiroi:runner:command-result:{command_id}")
        return RunnerCommandResult.model_validate_json(value) if value else None

    async def _result(
        self,
        command: RunnerCommand,
        *,
        status: str,
        payload: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        result = RunnerCommandResult(
            commandId=command.command_id,
            status=status,
            payload=payload or {},
            error=error,
        )
        await self.client.set(
            f"oneiroi:runner:command-result:{command.command_id}",
            result.model_dump_json(by_alias=True),
            ex=86_400,
        )
        await self._publish_result(result)

    async def _publish_result(self, result: RunnerCommandResult) -> None:
        from oneiroi_common.runner_protocol import COMMAND_RESULT_STREAM_TEMPLATE

        await self.client.xadd(
            COMMAND_RESULT_STREAM_TEMPLATE.format(command_id=result.command_id),
            {"result": result.model_dump_json(by_alias=True)},
            maxlen=10,
            approximate=True,
        )

    async def _publish_job_event(
        self,
        job_id: str,
        event_type: str,
        payload: dict[str, Any],
    ) -> str:
        return await self.client.xadd(
            JOB_EVENT_STREAM_TEMPLATE.format(job_id=job_id),
            {"type": event_type, "payload": json.dumps(payload, separators=(",", ":"))},
            maxlen=10_000,
            approximate=True,
        )
