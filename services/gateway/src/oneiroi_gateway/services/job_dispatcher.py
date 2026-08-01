from typing import Protocol

from oneiroi_gateway.redis.control_streams import RedisDirectedStreams
from oneiroi_gateway.services.job_scheduler import SlotReservation


class JobDispatcher(Protocol):
    async def dispatch(
        self,
        reservation: SlotReservation,
        job_id: str,
        payload: dict[str, object],
    ) -> None: ...


class InMemoryJobDispatcher:
    def __init__(self) -> None:
        self.items: list[tuple[SlotReservation, str, dict[str, object]]] = []

    async def dispatch(
        self,
        reservation: SlotReservation,
        job_id: str,
        payload: dict[str, object],
    ) -> None:
        self.items.append((reservation, job_id, payload))


class RedisJobDispatcher:
    def __init__(self, streams: RedisDirectedStreams) -> None:
        self.streams = streams

    async def dispatch(
        self,
        reservation: SlotReservation,
        job_id: str,
        payload: dict[str, object],
    ) -> None:
        await self.streams.publish_job(
            reservation.slot_id,
            job_id,
            {**payload, "fencingToken": reservation.fencing_token},
        )
