import json
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Query, status
from fastapi.responses import StreamingResponse

from oneiroi_common.agent import (
    AgentCapabilitiesResponse,
    AgentMessageResponse,
    AgentRunCreate,
    AgentRunResponse,
    AgentThreadResponse,
)
from oneiroi_gateway.agent.runtime import AgentRuntime, AgentRuntimeError
from oneiroi_gateway.services.agent_capabilities import AgentCapabilityService


def create_agent_router(
    capabilities: AgentCapabilityService,
    runtime: AgentRuntime,
) -> APIRouter:
    router = APIRouter(tags=["agent"])

    @router.get(
        "/v1/agent/capabilities",
        response_model=AgentCapabilitiesResponse,
        response_model_by_alias=True,
    )
    async def get_capabilities() -> AgentCapabilitiesResponse:
        return capabilities.get()

    @router.get(
        "/v1/conversations/{conversation_id}/agent/thread",
        response_model=AgentThreadResponse,
        response_model_by_alias=True,
    )
    async def get_thread(
        conversation_id: str,
        user: Annotated[str, Header(alias="X-Oneiroi-User")] = "demo-user",
    ) -> AgentThreadResponse:
        try:
            return await runtime.get_thread(user, conversation_id)
        except KeyError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from exc

    @router.get(
        "/v1/agent/threads/{thread_id}/messages",
        response_model=list[AgentMessageResponse],
        response_model_by_alias=True,
    )
    async def list_messages(
        thread_id: str,
        user: Annotated[str, Header(alias="X-Oneiroi-User")] = "demo-user",
        after: Annotated[int, Query(ge=0)] = 0,
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
    ) -> list[AgentMessageResponse]:
        try:
            return await runtime.list_messages(user, thread_id, after, limit)
        except KeyError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from exc

    @router.post(
        "/v1/agent/runs",
        response_model=AgentRunResponse,
        response_model_by_alias=True,
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def create_run(
        payload: AgentRunCreate,
        user: Annotated[str, Header(alias="X-Oneiroi-User")] = "demo-user",
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    ) -> AgentRunResponse:
        try:
            return await runtime.create_run(user, payload, idempotency_key or "")
        except KeyError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from exc
        except AgentRuntimeError as exc:
            raise _http_error(exc) from exc

    @router.get(
        "/v1/agent/runs/{run_id}",
        response_model=AgentRunResponse,
        response_model_by_alias=True,
    )
    async def get_run(
        run_id: str,
        user: Annotated[str, Header(alias="X-Oneiroi-User")] = "demo-user",
    ) -> AgentRunResponse:
        try:
            return await runtime.get_run(user, run_id)
        except KeyError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from exc

    @router.get("/v1/agent/runs/{run_id}/events")
    async def run_events(
        run_id: str,
        user: Annotated[str, Header(alias="X-Oneiroi-User")] = "demo-user",
        last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
    ) -> StreamingResponse:
        cursor = _event_cursor(last_event_id)
        try:
            await runtime.get_run(user, run_id)
        except KeyError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from exc

        async def stream() -> AsyncIterator[str]:
            async for event in runtime.events(user, run_id, cursor):
                if event is None:
                    yield ": heartbeat\n\n"
                    continue
                payload = json.dumps(
                    {
                        "runId": event.run_id,
                        "threadId": event.thread_id,
                        "sequence": event.sequence,
                        "data": event.payload,
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
                yield f"id: {event.id}\nevent: {event.event_type}\ndata: {payload}\n\n"

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @router.post(
        "/v1/agent/runs/{run_id}/cancel",
        response_model=AgentRunResponse,
        response_model_by_alias=True,
    )
    async def cancel_run(
        run_id: str,
        user: Annotated[str, Header(alias="X-Oneiroi-User")] = "demo-user",
    ) -> AgentRunResponse:
        try:
            return await runtime.cancel(user, run_id)
        except KeyError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from exc
        except AgentRuntimeError as exc:
            raise _http_error(exc) from exc

    return router


def _event_cursor(value: str | None) -> int:
    if value is None or value == "":
        return 0
    try:
        cursor = int(value)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "INVALID_EVENT_CURSOR", "message": "Last-Event-ID must be an integer."},
        ) from exc
    if cursor < 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "INVALID_EVENT_CURSOR", "message": "Last-Event-ID cannot be negative."},
        )
    return cursor


def _http_error(exc: AgentRuntimeError) -> HTTPException:
    return HTTPException(
        status_code=exc.status_code,
        detail={"code": exc.code, "message": exc.message},
    )
