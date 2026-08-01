import asyncio
import time
from contextlib import suppress

from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError

from oneiroi_common.runner_protocol import HEARTBEAT_STREAM, RunnerHeartbeat
from oneiroi_gateway.services.compute_sessions import ComputeSessionService


class RunnerHeartbeatMonitor:
    def __init__(
        self,
        redis_url: str,
        sessions: ComputeSessionService,
        *,
        timeout_seconds: float,
    ) -> None:
        from redis.asyncio import Redis

        self.client = Redis.from_url(redis_url, decode_responses=True)
        self.sessions = sessions
        self.timeout_seconds = timeout_seconds
        self.last_seen: dict[str, float] = {}
        self.started_at = time.monotonic()

    async def run(self, stop_event: asyncio.Event) -> None:
        cursor = "0-0"
        try:
            while not stop_event.is_set():
                try:
                    messages = await self.client.xread(
                        {HEARTBEAT_STREAM: cursor},
                        count=100,
                        block=max(1, int(min(self.timeout_seconds / 3, 1) * 1000)),
                    )
                except (RedisConnectionError, RedisTimeoutError):
                    await asyncio.sleep(min(self.timeout_seconds / 3, 1))
                    continue
                now = time.monotonic()
                if messages:
                    for message_id, fields in messages[0][1]:
                        cursor = message_id
                        heartbeat = RunnerHeartbeat.model_validate_json(fields["heartbeat"])
                        self.last_seen[heartbeat.gpu_id] = now
                active_gpu_ids = {
                    slot.gpu_id
                    for session in self.sessions.sessions.values()
                    for slot in session.slots
                    if slot.state.value not in {"empty", "error"}
                }
                stale = {
                    gpu_id
                    for gpu_id in active_gpu_ids
                    if now - self.last_seen.get(gpu_id, self.started_at)
                    >= self.timeout_seconds
                }
                if stale:
                    await self.sessions.reconcile_stale_gpus(stale)
                    for gpu_id in stale:
                        self.last_seen.pop(gpu_id, None)
                    self.started_at = now
        except asyncio.CancelledError:
            raise
        finally:
            await self.client.aclose()

    @staticmethod
    async def stop(task: asyncio.Task[None], stop_event: asyncio.Event) -> None:
        stop_event.set()
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
