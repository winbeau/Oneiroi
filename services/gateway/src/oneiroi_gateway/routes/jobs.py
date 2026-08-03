import json
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, status
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

from oneiroi_common.errors import OneiroiError
from oneiroi_common.jobs import JobStatus
from oneiroi_common.studio import JobCreate, JobResponse
from oneiroi_gateway.services.job_service import JobService


def create_job_router(jobs: JobService) -> APIRouter:
    router = APIRouter(prefix="/v1/jobs", tags=["jobs"])

    @router.get("", response_model=list[JobResponse], response_model_by_alias=True)
    async def list_jobs(
        user: Annotated[str, Header(alias="X-Oneiroi-User")] = "demo-user",
    ) -> list[JobResponse]:
        return await jobs.list(user)

    @router.post(
        "/i2v",
        response_model=JobResponse,
        response_model_by_alias=True,
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def create_job(
        payload: JobCreate,
        user: Annotated[str, Header(alias="X-Oneiroi-User")] = "demo-user",
    ) -> JobResponse:
        try:
            return await jobs.create(user, payload)
        except KeyError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from exc
        except OneiroiError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": exc.code.value, "message": exc.message},
            ) from exc
        except (RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    @router.get("/{job_id}", response_model=JobResponse, response_model_by_alias=True)
    async def get_job(
        job_id: str,
        user: Annotated[str, Header(alias="X-Oneiroi-User")] = "demo-user",
    ) -> JobResponse:
        try:
            return (await jobs.get(user, job_id)).response
        except KeyError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from exc

    @router.get("/{job_id}/events")
    async def job_events(
        job_id: str,
        user: Annotated[str, Header(alias="X-Oneiroi-User")] = "demo-user",
        last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
    ) -> StreamingResponse:
        try:
            await jobs.get(user, job_id)
        except KeyError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from exc

        async def stream() -> AsyncIterator[str]:
            async for event in jobs.events(user, job_id, int(last_event_id or 0)):
                if event is None:
                    yield ": heartbeat\n\n"
                    continue
                data = json.dumps(event.payload, ensure_ascii=False, separators=(",", ":"))
                yield f"id: {event.id}\nevent: {event.event_type}\ndata: {data}\n\n"

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @router.post("/{job_id}/cancel", response_model=JobResponse, response_model_by_alias=True)
    async def cancel_job(
        job_id: str,
        user: Annotated[str, Header(alias="X-Oneiroi-User")] = "demo-user",
    ) -> JobResponse:
        try:
            return await jobs.cancel(user, job_id)
        except KeyError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from exc

    @router.post("/{job_id}/retry", response_model=JobResponse, response_model_by_alias=True)
    async def retry_job(
        job_id: str,
        user: Annotated[str, Header(alias="X-Oneiroi-User")] = "demo-user",
    ) -> JobResponse:
        try:
            return await jobs.retry(user, job_id)
        except KeyError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from exc
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    @router.get("/{job_id}/file")
    async def get_job_file(
        job_id: str,
        user: Annotated[str, Header(alias="X-Oneiroi-User")] = "demo-user",
    ) -> FileResponse:
        try:
            stored = await jobs.get(user, job_id)
        except KeyError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from exc
        if stored.response.stage is not JobStatus.SUCCEEDED or stored.output_path is None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="JOB_NOT_COMPLETE")
        return FileResponse(
            stored.output_path,
            media_type="video/mp4",
            filename=f"{job_id}.mp4",
            headers={"Cache-Control": "public, max-age=31536000, immutable"},
        )

    @router.get("/{job_id}/manifest")
    async def get_job_manifest(
        job_id: str,
        user: Annotated[str, Header(alias="X-Oneiroi-User")] = "demo-user",
    ) -> JSONResponse:
        try:
            stored = await jobs.get(user, job_id)
        except KeyError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from exc
        if stored.response.stage is not JobStatus.SUCCEEDED or stored.manifest_path is None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="JOB_NOT_COMPLETE")
        manifest = json.loads(stored.manifest_path.read_text(encoding="utf-8"))
        return JSONResponse(_public_manifest(manifest))

    return router


def _public_manifest(value):
    if isinstance(value, dict):
        return {
            key: _public_manifest(item)
            for key, item in value.items()
            if "path" not in key.lower()
        }
    if isinstance(value, list):
        return [_public_manifest(item) for item in value]
    return value
