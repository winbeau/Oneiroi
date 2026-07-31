import json
from typing import Any

CONTROL_STREAM_TEMPLATE = "oneiroi:slot:{slot_id}:control"
JOB_STREAM_TEMPLATE = "oneiroi:slot:{slot_id}:jobs"
JOB_EVENT_STREAM_TEMPLATE = "oneiroi:job:{job_id}:events"


class RedisDirectedStreams:
    def __init__(self, redis_url: str) -> None:
        from redis.asyncio import Redis

        self.client = Redis.from_url(redis_url, decode_responses=True)

    async def publish_control(
        self,
        slot_id: str,
        command_type: str,
        payload: dict[str, Any],
    ) -> str:
        return await self.client.xadd(
            CONTROL_STREAM_TEMPLATE.format(slot_id=slot_id),
            {"type": command_type, "payload": json.dumps(payload, separators=(",", ":"))},
        )

    async def publish_job(self, slot_id: str, job_id: str, payload: dict[str, Any]) -> str:
        return await self.client.xadd(
            JOB_STREAM_TEMPLATE.format(slot_id=slot_id),
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

    async def close(self) -> None:
        await self.client.aclose()
