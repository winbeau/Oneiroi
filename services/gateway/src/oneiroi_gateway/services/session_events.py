import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass(frozen=True, slots=True)
class SessionEvent:
    id: int
    session_id: str
    event_type: str
    payload: dict[str, object]
    created_at: str


class SessionEventService:
    def __init__(self) -> None:
        self._events: dict[str, list[SessionEvent]] = {}
        self._conditions: dict[str, asyncio.Condition] = {}
        self._next_id = 1

    async def emit(
        self,
        session_id: str,
        event_type: str,
        payload: dict[str, object],
    ) -> SessionEvent:
        event = SessionEvent(
            id=self._next_id,
            session_id=session_id,
            event_type=event_type,
            payload=payload,
            created_at=datetime.now(UTC).isoformat(),
        )
        self._next_id += 1
        self._events.setdefault(session_id, []).append(event)
        condition = self._conditions.setdefault(session_id, asyncio.Condition())
        async with condition:
            condition.notify_all()
        return event

    def since(self, session_id: str, after_id: int = 0) -> list[SessionEvent]:
        return [event for event in self._events.get(session_id, []) if event.id > after_id]

    async def stream(self, session_id: str, after_id: int = 0) -> AsyncIterator[SessionEvent]:
        cursor = after_id
        condition = self._conditions.setdefault(session_id, asyncio.Condition())
        while True:
            pending = self.since(session_id, cursor)
            if pending:
                for event in pending:
                    cursor = event.id
                    yield event
                if pending[-1].event_type in {"compute.session.released", "compute.session.failed"}:
                    return
                continue
            async with condition:
                try:
                    await asyncio.wait_for(condition.wait(), timeout=15)
                except TimeoutError:
                    yield SessionEvent(
                        id=cursor,
                        session_id=session_id,
                        event_type="heartbeat",
                        payload={},
                        created_at=datetime.now(UTC).isoformat(),
                    )
