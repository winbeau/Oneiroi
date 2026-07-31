import json
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import uuid4

from fastapi import APIRouter, Header, HTTPException, Response, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from oneiroi_common.jobs import JobStatus, QueueTier


def utc_now() -> datetime:
    return datetime.now(UTC)


class MediaReference(BaseModel):
    name: str
    url: str


class GenerationDraft(BaseModel):
    mode: Literal["I2V"] = "I2V"
    prompt: str = Field(min_length=1, max_length=4000)
    quality: Literal["快速", "高质量"] = "快速"
    ratio: Literal["16:9", "9:16", "1:1"] = "16:9"
    resolution: Literal["720p", "1080p"] = "720p"
    duration: Literal[5, 8, 10] = 5
    seed: int = 42
    firstStrength: float = Field(default=1, ge=0, le=1)
    lastStrength: float = Field(default=1, ge=0, le=1)
    enhancePrompt: bool = False
    negativePrompt: str = ""
    queue: QueueTier = QueueTier.FAST
    quantization: Literal["fp8-cast", "none"] = "fp8-cast"
    offload: Literal["none", "cpu"] = "none"
    firstFrame: MediaReference | None = None
    lastFrame: MediaReference | None = None


class AssetCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    type: Literal["image", "template"] = "image"
    previewUrl: str = Field(min_length=1)
    draft: GenerationDraft | None = None


class AssetResponse(BaseModel):
    id: str
    type: Literal["image", "video", "template"]
    title: str
    createdAt: datetime
    previewUrl: str
    sourceJobId: str | None = None
    draft: GenerationDraft | None = None


class ConversationCreate(BaseModel):
    title: str = Field(default="未命名创作", min_length=1, max_length=100)


class ConversationResponse(BaseModel):
    id: str
    title: str
    updatedAt: datetime


class JobCreate(BaseModel):
    conversationId: str
    draft: GenerationDraft


class JobResponse(BaseModel):
    id: str
    conversationId: str
    createdAt: datetime
    updatedAt: datetime
    stage: JobStatus
    progress: int = Field(ge=0, le=100)
    draft: GenerationDraft
    previewUrl: str | None = None
    errorMessage: str | None = None


@dataclass
class StoredJob:
    response: JobResponse
    owner: str
    started_monotonic: float = field(default_factory=time.monotonic)
    cancelled: bool = False
    asset_created: bool = False


class StudioStore:
    _schedule = (
        (0.0, JobStatus.UPLOADED, 5),
        (0.6, JobStatus.QUEUED, 12),
        (1.2, JobStatus.ASSIGNED, 20),
        (2.0, JobStatus.PREPARING, 34),
        (3.0, JobStatus.GENERATING, 68),
        (4.3, JobStatus.ENCODING, 91),
        (5.3, JobStatus.SUCCEEDED, 100),
    )

    def __init__(self) -> None:
        self.assets: dict[str, tuple[str, AssetResponse]] = {}
        self.conversations: dict[str, tuple[str, ConversationResponse]] = {}
        self.jobs: dict[str, StoredJob] = {}

    def ensure_conversation(self, owner: str, conversation_id: str) -> ConversationResponse:
        existing = self.conversations.get(conversation_id)
        if existing is not None:
            existing_owner, conversation = existing
            if existing_owner != owner:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
            return conversation
        conversation = ConversationResponse(
            id=conversation_id,
            title="未命名创作",
            updatedAt=utc_now(),
        )
        self.conversations[conversation_id] = (owner, conversation)
        return conversation

    def current_job(self, owner: str, job_id: str) -> JobResponse:
        stored = self.jobs.get(job_id)
        if stored is None or stored.owner != owner:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="job not found")
        if stored.cancelled:
            return stored.response

        elapsed = time.monotonic() - stored.started_monotonic
        stage = JobStatus.DRAFT
        progress = 0
        for threshold, next_stage, next_progress in self._schedule:
            if elapsed >= threshold:
                stage = next_stage
                progress = next_progress
        response = stored.response.model_copy(
            update={
                "stage": stage,
                "progress": progress,
                "updatedAt": utc_now(),
                "previewUrl": (
                    stored.response.draft.lastFrame.url
                    if stage == JobStatus.SUCCEEDED and stored.response.draft.lastFrame
                    else stored.response.previewUrl
                ),
            }
        )
        stored.response = response

        if stage == JobStatus.SUCCEEDED and not stored.asset_created:
            asset = AssetResponse(
                id=f"asset-{uuid4().hex[:12]}",
                type="video",
                title="生成视频",
                createdAt=utc_now(),
                previewUrl=(
                    response.previewUrl
                    or (response.draft.firstFrame.url if response.draft.firstFrame else "")
                ),
                sourceJobId=response.id,
                draft=response.draft,
            )
            self.assets[asset.id] = (owner, asset)
            stored.asset_created = True
        return response


def get_user(
    x_oneiroi_user: Annotated[str | None, Header()] = None,
) -> str:
    return (x_oneiroi_user or "demo-user").strip() or "demo-user"


def create_studio_router(store: StudioStore) -> APIRouter:
    router = APIRouter(prefix="/v1", tags=["studio"])

    @router.get("/assets", response_model=list[AssetResponse])
    async def list_assets(
        user: Annotated[str, Header(alias="X-Oneiroi-User")] = "demo-user",
    ) -> list[AssetResponse]:
        return [asset for owner, asset in store.assets.values() if owner == user]

    @router.post("/assets", response_model=AssetResponse, status_code=status.HTTP_201_CREATED)
    async def create_asset(
        payload: AssetCreate,
        user: Annotated[str, Header(alias="X-Oneiroi-User")] = "demo-user",
    ) -> AssetResponse:
        asset = AssetResponse(
            id=f"asset-{uuid4().hex[:12]}",
            type=payload.type,
            title=payload.title,
            createdAt=utc_now(),
            previewUrl=payload.previewUrl,
            draft=payload.draft,
        )
        store.assets[asset.id] = (user, asset)
        return asset

    @router.delete("/assets/{asset_id}", status_code=status.HTTP_204_NO_CONTENT)
    async def delete_asset(
        asset_id: str,
        user: Annotated[str, Header(alias="X-Oneiroi-User")] = "demo-user",
    ) -> Response:
        stored = store.assets.get(asset_id)
        if stored is None or stored[0] != user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        del store.assets[asset_id]
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @router.get("/conversations", response_model=list[ConversationResponse])
    async def list_conversations(
        user: Annotated[str, Header(alias="X-Oneiroi-User")] = "demo-user",
    ) -> list[ConversationResponse]:
        return [item for owner, item in store.conversations.values() if owner == user]

    @router.post(
        "/conversations",
        response_model=ConversationResponse,
        status_code=status.HTTP_201_CREATED,
    )
    async def create_conversation(
        payload: ConversationCreate,
        user: Annotated[str, Header(alias="X-Oneiroi-User")] = "demo-user",
    ) -> ConversationResponse:
        conversation = ConversationResponse(
            id=f"conversation-{uuid4().hex[:12]}",
            title=payload.title,
            updatedAt=utc_now(),
        )
        store.conversations[conversation.id] = (user, conversation)
        return conversation

    @router.post("/jobs/i2v", response_model=JobResponse, status_code=status.HTTP_202_ACCEPTED)
    async def create_job(
        payload: JobCreate,
        user: Annotated[str, Header(alias="X-Oneiroi-User")] = "demo-user",
    ) -> JobResponse:
        conversation = store.ensure_conversation(user, payload.conversationId)
        created_at = utc_now()
        job = JobResponse(
            id=f"job-{uuid4().hex[:12]}",
            conversationId=conversation.id,
            createdAt=created_at,
            updatedAt=created_at,
            stage=JobStatus.DRAFT,
            progress=0,
            draft=payload.draft,
        )
        store.jobs[job.id] = StoredJob(response=job, owner=user)
        conversation.updatedAt = created_at
        return job

    @router.get("/jobs/{job_id}", response_model=JobResponse)
    async def get_job(
        job_id: str,
        user: Annotated[str, Header(alias="X-Oneiroi-User")] = "demo-user",
    ) -> JobResponse:
        return store.current_job(user, job_id)

    @router.get("/jobs/{job_id}/events")
    async def job_events(job_id: str, user: str = "demo-user") -> StreamingResponse:
        store.current_job(user, job_id)

        async def events() -> AsyncIterator[str]:
            import asyncio

            previous: JobStatus | None = None
            while True:
                job = store.current_job(user, job_id)
                if job.stage != previous:
                    payload = job.model_dump(mode="json")
                    yield f"event: job\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
                    previous = job.stage
                if job.stage.is_terminal:
                    break
                await asyncio.sleep(0.35)

        return StreamingResponse(
            events(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @router.post("/jobs/{job_id}/cancel", response_model=JobResponse)
    async def cancel_job(
        job_id: str,
        user: Annotated[str, Header(alias="X-Oneiroi-User")] = "demo-user",
    ) -> JobResponse:
        stored = store.jobs.get(job_id)
        if stored is None or stored.owner != user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        if not stored.response.stage.is_terminal:
            stored.cancelled = True
            stored.response = stored.response.model_copy(
                update={"stage": JobStatus.CANCELLED, "updatedAt": utc_now()}
            )
        return stored.response

    @router.get("/jobs/{job_id}/file")
    async def download_job_manifest(
        job_id: str,
        user: Annotated[str, Header(alias="X-Oneiroi-User")] = "demo-user",
    ) -> Response:
        job = store.current_job(user, job_id)
        if job.stage != JobStatus.SUCCEEDED:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="job is not complete")
        body = json.dumps(job.model_dump(mode="json"), ensure_ascii=False, indent=2)
        return Response(
            content=body,
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{job.id}.json"'},
        )

    return router
