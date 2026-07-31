import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from oneiroi_common.studio import (
    AssetResponse,
    ConversationResponse,
    JobEventResponse,
    JobResponse,
)


def utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(slots=True)
class StoredAsset:
    owner_id: str
    response: AssetResponse
    storage_path: Path
    sha256: str


@dataclass(slots=True)
class StoredJob:
    owner_id: str
    response: JobResponse
    manifest_path: Path | None = None
    output_path: Path | None = None


@dataclass(frozen=True, slots=True)
class JobAttemptRecord:
    id: str
    job_id: str
    attempt: int
    slot_id: str
    gpu_id: str
    runner_id: str | None
    worker_pid: int | None
    warm_start: bool | None
    status: str
    error_code: str | None
    created_at: datetime
    finished_at: datetime | None = None


class StudioRepository(Protocol):
    async def create_conversation(self, owner_id: str, title: str) -> ConversationResponse: ...

    async def list_conversations(self, owner_id: str) -> list[ConversationResponse]: ...

    async def get_conversation(
        self,
        owner_id: str,
        conversation_id: str,
    ) -> ConversationResponse: ...

    async def put_conversation(
        self, owner_id: str, conversation_id: str, title: str
    ) -> ConversationResponse: ...

    async def create_asset(self, asset: StoredAsset) -> AssetResponse: ...

    async def list_assets(self, owner_id: str) -> list[AssetResponse]: ...

    async def get_asset(self, owner_id: str, asset_id: str) -> StoredAsset: ...

    async def delete_asset(self, owner_id: str, asset_id: str) -> None: ...

    async def create_job(self, job: StoredJob) -> JobResponse: ...

    async def list_jobs(self, owner_id: str) -> list[JobResponse]: ...

    async def get_job(self, owner_id: str, job_id: str) -> StoredJob: ...

    async def update_job(self, job: StoredJob) -> JobResponse: ...

    async def add_attempt(self, attempt: JobAttemptRecord) -> None: ...

    async def list_attempts(self, job_id: str) -> list[JobAttemptRecord]: ...

    async def add_event(
        self, owner_id: str, job_id: str, event_type: str, payload: dict[str, object]
    ) -> JobEventResponse: ...

    async def list_events(
        self, owner_id: str, job_id: str, after_id: int = 0
    ) -> list[JobEventResponse]: ...


class InMemoryStudioRepository:
    def __init__(self) -> None:
        self.conversations: dict[str, tuple[str, ConversationResponse]] = {}
        self.assets: dict[str, StoredAsset] = {}
        self.jobs: dict[str, StoredJob] = {}
        self.attempts: dict[str, list[JobAttemptRecord]] = {}
        self.events: dict[str, list[JobEventResponse]] = {}
        self._event_id = 1
        self._lock = asyncio.Lock()

    async def create_conversation(self, owner_id: str, title: str) -> ConversationResponse:
        now = utc_now()
        response = ConversationResponse(
            id=f"conversation-{uuid4().hex[:16]}",
            title=title,
            createdAt=now,
            updatedAt=now,
        )
        async with self._lock:
            self.conversations[response.id] = (owner_id, response)
        return response

    async def list_conversations(self, owner_id: str) -> list[ConversationResponse]:
        return sorted(
            [
                item.model_copy(deep=True)
                for owner, item in self.conversations.values()
                if owner == owner_id
            ],
            key=lambda item: item.updated_at,
            reverse=True,
        )

    async def get_conversation(self, owner_id: str, conversation_id: str) -> ConversationResponse:
        stored = self.conversations.get(conversation_id)
        if stored is None or stored[0] != owner_id:
            raise KeyError(conversation_id)
        return stored[1].model_copy(deep=True)

    async def put_conversation(
        self,
        owner_id: str,
        conversation_id: str,
        title: str,
    ) -> ConversationResponse:
        stored = self.conversations.get(conversation_id)
        if stored is None or stored[0] != owner_id:
            raise KeyError(conversation_id)
        updated = stored[1].model_copy(update={"title": title, "updated_at": utc_now()})
        async with self._lock:
            self.conversations[conversation_id] = (owner_id, updated)
        return updated.model_copy(deep=True)

    async def create_asset(self, asset: StoredAsset) -> AssetResponse:
        async with self._lock:
            self.assets[asset.response.id] = asset
        return asset.response.model_copy(deep=True)

    async def list_assets(self, owner_id: str) -> list[AssetResponse]:
        return sorted(
            [
                asset.response.model_copy(deep=True)
                for asset in self.assets.values()
                if asset.owner_id == owner_id
            ],
            key=lambda item: item.created_at,
            reverse=True,
        )

    async def get_asset(self, owner_id: str, asset_id: str) -> StoredAsset:
        asset = self.assets.get(asset_id)
        if asset is None or asset.owner_id != owner_id:
            raise KeyError(asset_id)
        return asset

    async def delete_asset(self, owner_id: str, asset_id: str) -> None:
        await self.get_asset(owner_id, asset_id)
        async with self._lock:
            del self.assets[asset_id]

    async def create_job(self, job: StoredJob) -> JobResponse:
        async with self._lock:
            self.jobs[job.response.id] = job
        return job.response.model_copy(deep=True)

    async def list_jobs(self, owner_id: str) -> list[JobResponse]:
        return sorted(
            [
                job.response.model_copy(deep=True)
                for job in self.jobs.values()
                if job.owner_id == owner_id
            ],
            key=lambda item: item.created_at,
            reverse=True,
        )

    async def get_job(self, owner_id: str, job_id: str) -> StoredJob:
        job = self.jobs.get(job_id)
        if job is None or job.owner_id != owner_id:
            raise KeyError(job_id)
        return job

    async def update_job(self, job: StoredJob) -> JobResponse:
        async with self._lock:
            self.jobs[job.response.id] = job
        return job.response.model_copy(deep=True)

    async def add_attempt(self, attempt: JobAttemptRecord) -> None:
        async with self._lock:
            self.attempts.setdefault(attempt.job_id, []).append(attempt)

    async def list_attempts(self, job_id: str) -> list[JobAttemptRecord]:
        return list(self.attempts.get(job_id, []))

    async def add_event(
        self,
        owner_id: str,
        job_id: str,
        event_type: str,
        payload: dict[str, object],
    ) -> JobEventResponse:
        await self.get_job(owner_id, job_id)
        async with self._lock:
            event = JobEventResponse(
                id=self._event_id,
                jobId=job_id,
                eventType=event_type,
                payload=payload,
                createdAt=utc_now(),
            )
            self._event_id += 1
            self.events.setdefault(job_id, []).append(event)
        return event

    async def list_events(
        self,
        owner_id: str,
        job_id: str,
        after_id: int = 0,
    ) -> list[JobEventResponse]:
        await self.get_job(owner_id, job_id)
        return [
            event.model_copy(deep=True)
            for event in self.events.get(job_id, [])
            if event.id > after_id
        ]
