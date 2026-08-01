import asyncio
import json
import time
from typing import Any

from oneiroi_common.runner_protocol import (
    COMMAND_RESULT_STREAM_TEMPLATE,
    JOB_EVENT_STREAM_TEMPLATE,
    RUNNER_CONTROL_STREAM_TEMPLATE,
    SLOT_CONTROL_STREAM_TEMPLATE,
    SLOT_JOB_STREAM_TEMPLATE,
    RunnerCommand,
    RunnerCommandResult,
)

CONTROL_STREAM_TEMPLATE = SLOT_CONTROL_STREAM_TEMPLATE
JOB_STREAM_TEMPLATE = SLOT_JOB_STREAM_TEMPLATE


class RedisDirectedStreams:
    def __init__(self, redis_url: str) -> None:
        from redis.asyncio import Redis

        self.client = Redis.from_url(redis_url, decode_responses=True)

    async def publish_runner_command(self, gpu_id: str, command: RunnerCommand) -> str:
        return await self.client.xadd(
            RUNNER_CONTROL_STREAM_TEMPLATE.format(gpu_id=gpu_id),
            {"command": command.model_dump_json(by_alias=True)},
            maxlen=1_000,
            approximate=True,
        )

    async def publish_slot_command(self, command: RunnerCommand) -> str:
        return await self.client.xadd(
            SLOT_CONTROL_STREAM_TEMPLATE.format(slot_id=command.slot_id),
            {"command": command.model_dump_json(by_alias=True)},
            maxlen=1_000,
            approximate=True,
        )

    async def publish_control(
        self,
        slot_id: str,
        command_type: str,
        payload: dict[str, Any],
    ) -> str:
        return await self.client.xadd(
            SLOT_CONTROL_STREAM_TEMPLATE.format(slot_id=slot_id),
            {"type": command_type, "payload": json.dumps(payload, separators=(",", ":"))},
        )

    async def publish_command_result(self, result: RunnerCommandResult) -> str:
        stream = COMMAND_RESULT_STREAM_TEMPLATE.format(command_id=result.command_id)
        return await self.client.xadd(
            stream,
            {"result": result.model_dump_json(by_alias=True)},
            maxlen=10,
            approximate=True,
        )

    async def wait_command_result(
        self,
        command_id: str,
        *,
        timeout_seconds: float,
    ) -> RunnerCommandResult:
        stream = COMMAND_RESULT_STREAM_TEMPLATE.format(command_id=command_id)
        deadline = time.monotonic() + timeout_seconds
        cursor = "0-0"
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"runner command timed out: {command_id}")
            messages = await self.client.xread(
                {stream: cursor},
                count=1,
                block=max(1, int(min(remaining, 1) * 1000)),
            )
            if not messages:
                await asyncio.sleep(0)
                continue
            _, entries = messages[0]
            message_id, fields = entries[0]
            cursor = message_id
            result = RunnerCommandResult.model_validate_json(fields["result"])
            await self.client.delete(stream)
            return result

    async def publish_job(self, slot_id: str, job_id: str, payload: dict[str, Any]) -> str:
        return await self.client.xadd(
            SLOT_JOB_STREAM_TEMPLATE.format(slot_id=slot_id),
            {"jobId": job_id, "payload": json.dumps(payload, separators=(",", ":"))},
        )

    async def publish_job_event(
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

    async def read_job_events(
        self,
        job_id: str,
        after_id: str,
        *,
        block_milliseconds: int = 1_000,
    ) -> list[tuple[str, str, dict[str, Any]]]:
        messages = await self.client.xread(
            {JOB_EVENT_STREAM_TEMPLATE.format(job_id=job_id): after_id},
            count=100,
            block=block_milliseconds,
        )
        if not messages:
            return []
        return [
            (message_id, fields["type"], json.loads(fields["payload"]))
            for message_id, fields in messages[0][1]
        ]

    async def close(self) -> None:
        await self.client.aclose()
