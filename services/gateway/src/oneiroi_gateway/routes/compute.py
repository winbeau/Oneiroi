import json
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Query, status
from fastapi.responses import StreamingResponse

from oneiroi_common.compute import (
    ComputeCapabilitiesResponse,
    ComputeSessionCreate,
    ComputeSessionRelease,
    ComputeSessionSnapshot,
    GpuInventoryResponse,
)
from oneiroi_gateway.audit import audit_event
from oneiroi_gateway.services.capabilities import CapabilityService
from oneiroi_gateway.services.compute_sessions import ComputeSessionService
from oneiroi_gateway.services.gpu_inventory import GpuInventoryService


def create_compute_router(
    inventory: GpuInventoryService,
    sessions: ComputeSessionService,
    capabilities: CapabilityService,
) -> APIRouter:
    router = APIRouter(prefix="/v1/compute", tags=["compute"])

    @router.get("/gpus", response_model=GpuInventoryResponse, response_model_by_alias=True)
    async def get_gpus() -> GpuInventoryResponse:
        return await inventory.snapshot()

    @router.get(
        "/capabilities",
        response_model=ComputeCapabilitiesResponse,
        response_model_by_alias=True,
    )
    async def get_capabilities(
        session_id: Annotated[str | None, Query(alias="sessionId")] = None,
        user: Annotated[str, Header(alias="X-Oneiroi-User")] = "demo-user",
    ) -> ComputeCapabilitiesResponse:
        session = None
        if session_id:
            try:
                session = sessions.get(user, session_id)
            except KeyError as exc:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from exc
        return capabilities.get(session)

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
            session = await sessions.create(user, payload, idempotency_key)
        except (ValueError, RuntimeError) as exc:
            audit_event(
                "compute.create",
                user,
                outcome="failed",
                reason=type(exc).__name__,
            )
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
        audit_event("compute.create", user, resource_id=session.id, outcome="succeeded")
        return session

    @router.get(
        "/sessions/current",
        response_model=ComputeSessionSnapshot | None,
        response_model_by_alias=True,
    )
    async def get_current_session(
        user: Annotated[str, Header(alias="X-Oneiroi-User")] = "demo-user",
    ) -> ComputeSessionSnapshot | None:
        return sessions.current(user)

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
            session = await sessions.release(user, session_id, payload)
        except KeyError as exc:
            audit_event(
                "compute.release",
                user,
                resource_id=session_id,
                outcome="failed",
                reason="NOT_FOUND",
            )
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from exc
        except ValueError as exc:
            audit_event(
                "compute.release",
                user,
                resource_id=session_id,
                outcome="failed",
                reason=type(exc).__name__,
            )
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
        audit_event(
            "compute.release",
            user,
            resource_id=session_id,
            outcome="succeeded" if session.state.value == "released" else "failed",
            reason=session.error_code,
        )
        return session

    return router
