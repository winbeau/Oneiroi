from dataclasses import dataclass
from typing import Annotated

import httpx
from fastapi import APIRouter, Header, HTTPException, Request, Response, status
from fastapi.responses import StreamingResponse

from oneiroi_bff.access_identity import (
    AccessAuthenticationError,
    AccessConfigurationError,
    AccessVerificationUnavailableError,
    CloudflareAccessJwtValidator,
)
from oneiroi_bff.gateway_client import GatewayClient
from oneiroi_bff.service_auth import (
    ServiceAssertionSigner,
    ServiceAssertionValidator,
    ServiceAuthConfigurationError,
    ServiceAuthenticationError,
)
from oneiroi_bff.settings import BffSettings
from oneiroi_common.identity import SERVICE_ASSERTION_HEADER

PASSTHROUGH_RESPONSE_HEADERS = {
    "accept-ranges",
    "cache-control",
    "content-disposition",
    "content-length",
    "content-range",
    "content-type",
    "etag",
    "last-modified",
    "retry-after",
    "x-request-id",
}
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


@dataclass(frozen=True)
class ResolvedIdentity:
    owner_id: str
    service_assertion: str | None


def create_proxy_router(gateway: GatewayClient, settings: BffSettings) -> APIRouter:
    router = APIRouter(tags=["gateway-proxy"])
    access_validator = CloudflareAccessJwtValidator(
        issuer=settings.access_issuer,
        audience=settings.access_audience,
        jwks_url=settings.access_jwks_url,
        cache_seconds=settings.access_jwks_cache_seconds,
        clock_skew_seconds=settings.access_clock_skew_seconds,
    )
    service_signer = ServiceAssertionSigner(
        settings.service_private_key_file,
        issuer=settings.service_assertion_issuer,
        audience=settings.service_assertion_audience,
        key_id=settings.service_assertion_key_id,
        lifetime_seconds=settings.service_assertion_lifetime_seconds,
    )
    service_validator = ServiceAssertionValidator(
        settings.service_public_key_file,
        issuer=settings.service_assertion_issuer,
        audience=settings.service_assertion_audience,
        clock_skew_seconds=settings.service_assertion_clock_skew_seconds,
    )

    async def identity(request: Request, header_user: str | None) -> ResolvedIdentity:
        try:
            if settings.require_inbound_service_auth:
                assertion = request.headers.get(SERVICE_ASSERTION_HEADER, "")
                owner_id = service_validator.validate(assertion)
                return ResolvedIdentity(owner_id=owner_id, service_assertion=assertion)
            if settings.environment == "development":
                cookie_user = request.cookies.get("oneiroi_user")
                owner_id = (header_user or cookie_user or "demo-user").strip() or "demo-user"
                assertion = (
                    service_signer.issue(owner_id)
                    if settings.service_private_key_file is not None
                    else None
                )
                return ResolvedIdentity(owner_id=owner_id, service_assertion=assertion)
            access_assertion = request.headers.get("Cf-Access-Jwt-Assertion", "")
            access_identity = await access_validator.validate(access_assertion)
            return ResolvedIdentity(
                owner_id=access_identity.owner_id,
                service_assertion=service_signer.issue(access_identity.owner_id),
            )
        except (AccessAuthenticationError, ServiceAuthenticationError) as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="AUTHENTICATION_REQUIRED",
            ) from exc
        except (
            AccessConfigurationError,
            AccessVerificationUnavailableError,
            ServiceAuthConfigurationError,
        ) as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="AUTHENTICATION_NOT_CONFIGURED",
            ) from exc

    def enforce_csrf(request: Request) -> None:
        if (
            request.method in SAFE_METHODS
            or settings.environment == "development"
            or settings.require_inbound_service_auth
        ):
            return
        origin = request.headers.get("origin", "").strip().rstrip("/")
        if not origin or origin not in settings.trusted_origins:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="CSRF_VALIDATION_FAILED",
            )

    async def forward(
        request: Request,
        path: str,
        header_user: str | None,
        *,
        maximum_bytes: int | None = None,
    ) -> Response:
        enforce_csrf(request)
        resolved = await identity(request, header_user)
        body = await _bounded_request_body(request, maximum_bytes or settings.max_upload_bytes)
        headers = _request_headers(request, resolved)
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
            headers=_response_headers(upstream.headers),
            media_type=None,
        )

    async def forward_stream(
        request: Request,
        path: str,
        header_user: str | None,
    ) -> Response:
        resolved = await identity(request, header_user)
        headers = _request_headers(request, resolved)
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
            headers=_response_headers(upstream_headers),
            media_type=None,
        )

    async def forward_events(
        request: Request,
        path: str,
        header_user: str | None,
    ) -> Response:
        resolved = await identity(request, header_user)
        headers = _request_headers(request, resolved)
        try:
            upstream_status, upstream_headers, body = await gateway.stream(
                request.method,
                path,
                headers=headers,
                query=request.url.query,
            )
        except (httpx.ConnectError, httpx.TimeoutException):
            return Response(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
        response_headers = _response_headers(upstream_headers)
        response_headers.update({"cache-control": "no-cache", "x-accel-buffering": "no"})
        return StreamingResponse(
            body,
            status_code=upstream_status,
            headers=response_headers,
            media_type=None,
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

    @router.get("/v1/agent/capabilities")
    async def agent_capabilities(
        request: Request,
        user: Annotated[str | None, Header(alias="X-Oneiroi-User")] = None,
    ) -> Response:
        return await forward(request, "/v1/agent/capabilities", user)

    @router.get("/v1/conversations/{conversation_id}/agent/thread")
    async def agent_thread(
        conversation_id: str,
        request: Request,
        user: Annotated[str | None, Header(alias="X-Oneiroi-User")] = None,
    ) -> Response:
        return await forward(request, f"/v1/conversations/{conversation_id}/agent/thread", user)

    @router.get("/v1/agent/threads/{thread_id}/messages")
    async def agent_messages(
        thread_id: str,
        request: Request,
        user: Annotated[str | None, Header(alias="X-Oneiroi-User")] = None,
    ) -> Response:
        return await forward(request, f"/v1/agent/threads/{thread_id}/messages", user)

    @router.post("/v1/agent/runs")
    async def create_agent_run(
        request: Request,
        user: Annotated[str | None, Header(alias="X-Oneiroi-User")] = None,
    ) -> Response:
        return await forward(
            request,
            "/v1/agent/runs",
            user,
            maximum_bytes=settings.max_agent_json_bytes,
        )

    @router.get("/v1/agent/runs/{run_id}")
    async def agent_run(
        run_id: str,
        request: Request,
        user: Annotated[str | None, Header(alias="X-Oneiroi-User")] = None,
    ) -> Response:
        return await forward(request, f"/v1/agent/runs/{run_id}", user)

    @router.get("/v1/agent/runs/{run_id}/events")
    async def agent_run_events(
        run_id: str,
        request: Request,
        user: Annotated[str | None, Header(alias="X-Oneiroi-User")] = None,
    ) -> Response:
        return await forward_events(request, f"/v1/agent/runs/{run_id}/events", user)

    @router.post("/v1/agent/runs/{run_id}/cancel")
    async def cancel_agent_run(
        run_id: str,
        request: Request,
        user: Annotated[str | None, Header(alias="X-Oneiroi-User")] = None,
    ) -> Response:
        return await forward(
            request,
            f"/v1/agent/runs/{run_id}/cancel",
            user,
            maximum_bytes=settings.max_agent_json_bytes,
        )

    @router.post("/v1/agent/tool-calls/{tool_call_id}/approve")
    async def approve_agent_tool(
        tool_call_id: str,
        request: Request,
        user: Annotated[str | None, Header(alias="X-Oneiroi-User")] = None,
    ) -> Response:
        return await forward(
            request,
            f"/v1/agent/tool-calls/{tool_call_id}/approve",
            user,
            maximum_bytes=settings.max_agent_json_bytes,
        )

    @router.post("/v1/agent/tool-calls/{tool_call_id}/reject")
    async def reject_agent_tool(
        tool_call_id: str,
        request: Request,
        user: Annotated[str | None, Header(alias="X-Oneiroi-User")] = None,
    ) -> Response:
        return await forward(
            request,
            f"/v1/agent/tool-calls/{tool_call_id}/reject",
            user,
            maximum_bytes=settings.max_agent_json_bytes,
        )

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

    @router.get("/v1/compute/sessions/current")
    async def current_compute_session(
        request: Request,
        user: Annotated[str | None, Header(alias="X-Oneiroi-User")] = None,
    ) -> Response:
        return await forward(request, "/v1/compute/sessions/current", user)

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
        return await forward_stream(request, f"/v1/assets/{asset_id}/file", user)

    @router.delete("/v1/assets/{asset_id}")
    async def delete_asset(
        asset_id: str,
        request: Request,
        user: Annotated[str | None, Header(alias="X-Oneiroi-User")] = None,
    ) -> Response:
        return await forward(request, f"/v1/assets/{asset_id}", user)

    @router.get("/v1/jobs")
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
        return await forward_stream(request, f"/v1/jobs/{job_id}/file", user)

    @router.get("/v1/jobs/{job_id}/manifest")
    async def job_manifest(
        job_id: str,
        request: Request,
        user: Annotated[str | None, Header(alias="X-Oneiroi-User")] = None,
    ) -> Response:
        return await forward(request, f"/v1/jobs/{job_id}/manifest", user)

    return router


async def _bounded_request_body(request: Request, maximum_bytes: int) -> bytes:
    if content_length := request.headers.get("content-length"):
        try:
            if int(content_length) > maximum_bytes:
                raise HTTPException(status_code=status.HTTP_413_CONTENT_TOO_LARGE)
        except ValueError:
            pass
    chunks: list[bytes] = []
    received = 0
    async for chunk in request.stream():
        received += len(chunk)
        if received > maximum_bytes:
            raise HTTPException(status_code=status.HTTP_413_CONTENT_TOO_LARGE)
        chunks.append(chunk)
    return b"".join(chunks)


def _request_headers(request: Request, identity: ResolvedIdentity) -> dict[str, str]:
    headers = {"X-Oneiroi-User": identity.owner_id}
    if identity.service_assertion:
        headers[SERVICE_ASSERTION_HEADER] = identity.service_assertion
    for name in (
        "content-type",
        "idempotency-key",
        "if-none-match",
        "if-range",
        "last-event-id",
        "range",
    ):
        if value := request.headers.get(name):
            headers[name] = value
    return headers


def _response_headers(headers: httpx.Headers | dict[str, str]) -> dict[str, str]:
    return {
        key: value for key, value in headers.items() if key.lower() in PASSTHROUGH_RESPONSE_HEADERS
    }
