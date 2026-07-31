import json
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, status
from fastapi.responses import StreamingResponse

from oneiroi_common.compute import (
    ComputeSessionCreate,
    ComputeSessionRelease,
    ComputeSessionSnapshot,
    GpuInventoryResponse,
)
from oneiroi_gateway.services.compute_sessions import ComputeSessionService
from oneiroi_gateway.services.gpu_inventory import GpuInventoryService


def create_compute_router(
    inventory: GpuInventoryService,
    sessions: ComputeSessionService,
) -> APIRouter:
    router = APIRouter(prefix="/v1/compute", tags=["compute"])

    @router.get("/gpus", response_model=GpuInventoryResponse, response_model_by_alias=True)
    async def get_gpus() -> GpuInventoryResponse:
        return await inventory.snapshot()

    @router.post(
        "/sessions",
        response_model=ComputeSessionSnapshot,
        response_model_by_alias=True,
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def create_session(
        payload: ComputeSessionCreate,
        user: Annotated[str, Header(alias="X-Oneiroi-User")] = "demo-user",
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    ) -> ComputeSessionSnapshot:
        try:
            return await sessions.create(user, payload, idempotency_key)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    @router.get(
        "/sessions/{session_id}",
        response_model=ComputeSessionSnapshot,
        response_model_by_alias=True,
    )
    async def get_session(
        session_id: str,
        user: Annotated[str, Header(alias="X-Oneiroi-User")] = "demo-user",
    ) -> ComputeSessionSnapshot:
        try:
            return sessions.get(user, session_id)
        except KeyError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from exc

    @router.get("/sessions/{session_id}/events")
    async def session_events(
        session_id: str,
        user: Annotated[str, Header(alias="X-Oneiroi-User")] = "demo-user",
        last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
    ) -> StreamingResponse:
        try:
            sessions.get(user, session_id)
        except KeyError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from exc

        async def stream() -> AsyncIterator[str]:
            after_id = int(last_event_id or 0)
            async for event in sessions.events.stream(session_id, after_id):
                if event.event_type == "heartbeat":
                    yield ": heartbeat\n\n"
                    continue
                payload = json.dumps(event.payload, ensure_ascii=False, separators=(",", ":"))
                yield f"id: {event.id}\nevent: {event.event_type}\ndata: {payload}\n\n"

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @router.post(
        "/sessions/{session_id}/release",
        response_model=ComputeSessionSnapshot,
        response_model_by_alias=True,
    )
    async def release_session(
        session_id: str,
        payload: ComputeSessionRelease,
        user: Annotated[str, Header(alias="X-Oneiroi-User")] = "demo-user",
    ) -> ComputeSessionSnapshot:
        try:
            return await sessions.release(user, session_id, payload)
        except KeyError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from exc
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    return router
