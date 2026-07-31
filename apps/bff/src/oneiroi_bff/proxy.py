from typing import Annotated

import httpx
from fastapi import APIRouter, Header, Request, Response, status
from fastapi.responses import StreamingResponse

from oneiroi_bff.gateway_client import GatewayClient
from oneiroi_bff.settings import BffSettings

PASSTHROUGH_RESPONSE_HEADERS = {"content-type", "content-disposition", "cache-control"}


def create_proxy_router(gateway: GatewayClient, settings: BffSettings) -> APIRouter:
    router = APIRouter(tags=["gateway-proxy"])

    def identity(request: Request, header_user: str | None) -> str:
        cookie_user = request.cookies.get("oneiroi_user")
        if settings.environment == "development":
            return (header_user or cookie_user or "demo-user").strip() or "demo-user"
        return (cookie_user or "").strip()

    async def forward(
        request: Request,
        path: str,
        header_user: str | None,
    ) -> Response:
        body = await request.body()
        if len(body) > settings.max_upload_bytes:
            return Response(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)
        headers = _request_headers(request, identity(request, header_user))
        try:
            upstream = await gateway.request(
                request.method,
                path,
                content=body,
                headers=headers,
                query=request.url.query,
            )
        except (httpx.ConnectError, httpx.TimeoutException):
            return Response(
                content=b'{"detail":"GATEWAY_UNAVAILABLE"}',
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                media_type="application/json",
            )
        return Response(
            content=upstream.content,
            status_code=upstream.status_code,
            headers={
                key: value
                for key, value in upstream.headers.items()
                if key.lower() in PASSTHROUGH_RESPONSE_HEADERS
            },
            media_type=None,
        )

    async def forward_events(
        request: Request,
        path: str,
        header_user: str | None,
    ) -> Response:
        headers = _request_headers(request, identity(request, header_user))
        try:
            upstream_status, upstream_headers, body = await gateway.stream(
                request.method,
                path,
                headers=headers,
                query=request.url.query,
            )
        except (httpx.ConnectError, httpx.TimeoutException):
            return Response(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
        return StreamingResponse(
            body,
            status_code=upstream_status,
            media_type=upstream_headers.get("content-type", "text/event-stream"),
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @router.api_route("/v1/conversations", methods=["GET", "POST"])
    async def conversations(
        request: Request,
        user: Annotated[str | None, Header(alias="X-Oneiroi-User")] = None,
    ) -> Response:
        return await forward(request, "/v1/conversations", user)

    @router.api_route("/v1/conversations/{conversation_id}", methods=["GET", "PUT"])
    async def conversation(
        conversation_id: str,
        request: Request,
        user: Annotated[str | None, Header(alias="X-Oneiroi-User")] = None,
    ) -> Response:
        return await forward(request, f"/v1/conversations/{conversation_id}", user)

    @router.get("/v1/compute/gpus")
    async def compute_gpus(
        request: Request,
        user: Annotated[str | None, Header(alias="X-Oneiroi-User")] = None,
    ) -> Response:
        return await forward(request, "/v1/compute/gpus", user)

    @router.get("/v1/compute/capabilities")
    async def compute_capabilities(
        request: Request,
        user: Annotated[str | None, Header(alias="X-Oneiroi-User")] = None,
    ) -> Response:
        return await forward(request, "/v1/compute/capabilities", user)

    @router.post("/v1/compute/sessions")
    async def create_compute_session(
        request: Request,
        user: Annotated[str | None, Header(alias="X-Oneiroi-User")] = None,
    ) -> Response:
        return await forward(request, "/v1/compute/sessions", user)

    @router.get("/v1/compute/sessions/{session_id}")
    async def compute_session(
        session_id: str,
        request: Request,
        user: Annotated[str | None, Header(alias="X-Oneiroi-User")] = None,
    ) -> Response:
        return await forward(request, f"/v1/compute/sessions/{session_id}", user)

    @router.get("/v1/compute/sessions/{session_id}/events")
    async def compute_events(
        session_id: str,
        request: Request,
        user: Annotated[str | None, Header(alias="X-Oneiroi-User")] = None,
    ) -> Response:
        return await forward_events(request, f"/v1/compute/sessions/{session_id}/events", user)

    @router.post("/v1/compute/sessions/{session_id}/release")
    async def release_compute(
        session_id: str,
        request: Request,
        user: Annotated[str | None, Header(alias="X-Oneiroi-User")] = None,
    ) -> Response:
        return await forward(request, f"/v1/compute/sessions/{session_id}/release", user)

    @router.post("/v1/uploads/images")
    async def upload_image(
        request: Request,
        user: Annotated[str | None, Header(alias="X-Oneiroi-User")] = None,
    ) -> Response:
        return await forward(request, "/v1/uploads/images", user)

    @router.get("/v1/assets")
    async def assets(
        request: Request,
        user: Annotated[str | None, Header(alias="X-Oneiroi-User")] = None,
    ) -> Response:
        return await forward(request, "/v1/assets", user)

    @router.get("/v1/assets/{asset_id}/file")
    async def asset_file(
        asset_id: str,
        request: Request,
        user: Annotated[str | None, Header(alias="X-Oneiroi-User")] = None,
    ) -> Response:
        return await forward(request, f"/v1/assets/{asset_id}/file", user)

    @router.delete("/v1/assets/{asset_id}")
    async def delete_asset(
        asset_id: str,
        request: Request,
        user: Annotated[str | None, Header(alias="X-Oneiroi-User")] = None,
    ) -> Response:
        return await forward(request, f"/v1/assets/{asset_id}", user)

    @router.api_route("/v1/jobs", methods=["GET"])
    async def jobs(
        request: Request,
        user: Annotated[str | None, Header(alias="X-Oneiroi-User")] = None,
    ) -> Response:
        return await forward(request, "/v1/jobs", user)

    @router.post("/v1/jobs/i2v")
    async def create_job(
        request: Request,
        user: Annotated[str | None, Header(alias="X-Oneiroi-User")] = None,
    ) -> Response:
        return await forward(request, "/v1/jobs/i2v", user)

    @router.get("/v1/jobs/{job_id}")
    async def job(
        job_id: str,
        request: Request,
        user: Annotated[str | None, Header(alias="X-Oneiroi-User")] = None,
    ) -> Response:
        return await forward(request, f"/v1/jobs/{job_id}", user)

    @router.get("/v1/jobs/{job_id}/events")
    async def job_events(
        job_id: str,
        request: Request,
        user: Annotated[str | None, Header(alias="X-Oneiroi-User")] = None,
    ) -> Response:
        return await forward_events(request, f"/v1/jobs/{job_id}/events", user)

    @router.post("/v1/jobs/{job_id}/cancel")
    async def cancel_job(
        job_id: str,
        request: Request,
        user: Annotated[str | None, Header(alias="X-Oneiroi-User")] = None,
    ) -> Response:
        return await forward(request, f"/v1/jobs/{job_id}/cancel", user)

    @router.post("/v1/jobs/{job_id}/retry")
    async def retry_job(
        job_id: str,
        request: Request,
        user: Annotated[str | None, Header(alias="X-Oneiroi-User")] = None,
    ) -> Response:
        return await forward(request, f"/v1/jobs/{job_id}/retry", user)

    @router.get("/v1/jobs/{job_id}/file")
    async def job_file(
        job_id: str,
        request: Request,
        user: Annotated[str | None, Header(alias="X-Oneiroi-User")] = None,
    ) -> Response:
        return await forward(request, f"/v1/jobs/{job_id}/file", user)

    @router.get("/v1/jobs/{job_id}/manifest")
    async def job_manifest(
        job_id: str,
        request: Request,
        user: Annotated[str | None, Header(alias="X-Oneiroi-User")] = None,
    ) -> Response:
        return await forward(request, f"/v1/jobs/{job_id}/manifest", user)

    return router


def _request_headers(request: Request, user: str) -> dict[str, str]:
    headers = {"X-Oneiroi-User": user}
    for name in ("content-type", "idempotency-key", "last-event-id"):
        if value := request.headers.get(name):
            headers[name] = value
    return headers
