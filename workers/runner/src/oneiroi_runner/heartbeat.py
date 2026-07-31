import asyncio
from collections.abc import Awaitable, Callable
from typing import Protocol

from oneiroi_common.runner_protocol import RunnerHeartbeat

HEARTBEAT_STREAM = "oneiroi:runner:heartbeats"


class HeartbeatPublisher(Protocol):
    async def publish(self, heartbeat: RunnerHeartbeat) -> None: ...


class InMemoryHeartbeatPublisher:
    def __init__(self) -> None:
        self.items: list[RunnerHeartbeat] = []

    async def publish(self, heartbeat: RunnerHeartbeat) -> None:
        self.items.append(heartbeat)


class RedisHeartbeatPublisher:
    def __init__(self, redis_url: str) -> None:
        from redis.asyncio import Redis

        self.client = Redis.from_url(redis_url, decode_responses=True)

    async def publish(self, heartbeat: RunnerHeartbeat) -> None:
        await self.client.xadd(
            HEARTBEAT_STREAM,
            {"heartbeat": heartbeat.model_dump_json(by_alias=True)},
            maxlen=10_000,
            approximate=True,
        )

    async def close(self) -> None:
        await self.client.aclose()


async def heartbeat_loop(
    publisher: HeartbeatPublisher,
    heartbeat_factory: Callable[[], Awaitable[RunnerHeartbeat]],
    *,
    interval_seconds: float,
    stop_event: asyncio.Event,
) -> None:
    while not stop_event.is_set():
        await publisher.publish(await heartbeat_factory())
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval_seconds)
        except TimeoutError:
            continue
