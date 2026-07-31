import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from oneiroi_common.compute import FAST_PROFILE_ID, HQ_PROFILE_ID, ProfileTier
from oneiroi_common.jobs import JobStatus
from oneiroi_common.studio import (
    GpuAssignment,
    JobCreate,
    JobError,
    JobEventResponse,
    JobOutput,
    JobResponse,
)
from oneiroi_gateway.repositories.studio import (
    JobAttemptRecord,
    StoredJob,
    StudioRepository,
)
from oneiroi_gateway.services.artifact_service import ArtifactService
from oneiroi_gateway.services.capabilities import CapabilityService
from oneiroi_gateway.services.compute_sessions import ComputeSessionService
from oneiroi_gateway.services.job_dispatcher import JobDispatcher
from oneiroi_gateway.services.job_execution import JobExecutionResult, JobExecutor
from oneiroi_gateway.services.job_scheduler import JobScheduler, SlotReservation


def utc_now() -> datetime:
    return datetime.now(UTC)


class JobService:
    def __init__(
        self,
        repository: StudioRepository,
        sessions: ComputeSessionService,
        capabilities: CapabilityService,
        scheduler: JobScheduler,
        dispatcher: JobDispatcher,
        artifacts: ArtifactService,
        executor: JobExecutor | None = None,
    ) -> None:
        self.repository = repository
        self.sessions = sessions
        self.capabilities = capabilities
        self.scheduler = scheduler
        self.dispatcher = dispatcher
        self.artifacts = artifacts
        self.executor = executor
        self._conditions: dict[str, asyncio.Condition] = {}
        self._cancel_requested: set[str] = set()
        self._reservations: dict[str, SlotReservation] = {}
        self._tasks: set[asyncio.Task[None]] = set()

    async def create(self, owner_id: str, payload: JobCreate) -> JobResponse:
        await self.repository.get_conversation(owner_id, payload.conversation_id)
        session = self.sessions.get(owner_id, payload.compute_session_id)
        self.capabilities.require_profile(session, payload.draft.profile)
        input_paths = await self._input_paths(owner_id, payload)
        now = utc_now()
        profile_id = (
            HQ_PROFILE_ID if payload.draft.profile is ProfileTier.HQ else FAST_PROFILE_ID
        )
        response = JobResponse(
            id=f"job-{uuid4().hex[:20]}",
            conversationId=payload.conversation_id,
            computeSessionId=payload.compute_session_id,
            createdAt=now,
            updatedAt=now,
            stage=JobStatus.QUEUED,
            progress=10,
            draft=payload.draft,
            profileId=profile_id,
            attempt=1,
        )
        stored = StoredJob(owner_id=owner_id, response=response)
        await self.repository.create_job(stored)
        await self._event(stored, "job.queued")
        await self._assign_and_dispatch(stored, input_paths)
        return stored.response.model_copy(deep=True)

    async def list(self, owner_id: str) -> list[JobResponse]:
        return await self.repository.list_jobs(owner_id)

    async def get(self, owner_id: str, job_id: str) -> StoredJob:
        return await self.repository.get_job(owner_id, job_id)

    async def cancel(self, owner_id: str, job_id: str) -> JobResponse:
        stored = await self.repository.get_job(owner_id, job_id)
        if stored.response.stage.is_terminal:
            return stored.response
        self._cancel_requested.add(job_id)
        immediately_cancellable = stored.response.stage in {
            JobStatus.QUEUED,
            JobStatus.ASSIGNED,
        }
        if immediately_cancellable and self.executor is None:
            await self._update(stored, stage=JobStatus.CANCELLED, progress=stored.response.progress)
            await self._event(stored, "job.cancelled")
            reservation = self._reservations.pop(job_id, None)
            if reservation is not None:
                await self.scheduler.release(reservation)
        else:
            await self._update(
                stored,
                stage=JobStatus.CANCEL_REQUESTED,
                progress=stored.response.progress,
            )
            await self._event(stored, "job.cancel_requested")
        return stored.response.model_copy(deep=True)

    async def retry(self, owner_id: str, job_id: str) -> JobResponse:
        stored = await self.repository.get_job(owner_id, job_id)
        if stored.response.stage not in {JobStatus.FAILED, JobStatus.CANCELLED}:
            raise ValueError("JOB_NOT_RETRYABLE")
        attempts = await self.repository.list_attempts(job_id)
        next_attempt = len(attempts) + 1
        self._cancel_requested.discard(job_id)
        stored.response = stored.response.model_copy(
            update={
                "stage": JobStatus.QUEUED,
                "progress": 10,
                "attempt": next_attempt,
                "updated_at": utc_now(),
                "error": None,
                "output": None,
                "gpu": None,
            }
        )
        stored.output_path = None
        stored.manifest_path = None
        await self.repository.update_job(stored)
        await self._event(stored, "job.retry_queued")
        input_paths = await self._input_paths_from_draft(owner_id, stored.response.draft)
        await self._assign_and_dispatch(stored, input_paths)
        return stored.response.model_copy(deep=True)

    async def events(
        self,
        owner_id: str,
        job_id: str,
        after_id: int = 0,
    ) -> AsyncIterator[JobEventResponse | None]:
        await self.repository.get_job(owner_id, job_id)
        cursor = after_id
        condition = self._conditions.setdefault(job_id, asyncio.Condition())
        while True:
            events = await self.repository.list_events(owner_id, job_id, cursor)
            if events:
                for event in events:
                    cursor = event.id
                    yield event
                job = await self.repository.get_job(owner_id, job_id)
                if job.response.stage.is_terminal:
                    return
                continue
            async with condition:
                try:
                    await asyncio.wait_for(condition.wait(), timeout=15)
                except TimeoutError:
                    yield None

    async def _assign_and_dispatch(
        self,
        stored: StoredJob,
        input_paths: tuple[Path | None, Path | None],
    ) -> None:
        reservation = await self.scheduler.reserve(
            stored.owner_id,
            stored.response.compute_session_id,
            stored.response.draft.profile,
        )
        self._reservations[stored.response.id] = reservation
        stored.response = stored.response.model_copy(
            update={
                "stage": JobStatus.ASSIGNED,
                "progress": 18,
                "updated_at": utc_now(),
                "gpu": GpuAssignment(
                    id=reservation.gpu_id,
                    physicalIndex=reservation.physical_index,
                ),
            }
        )
        await self.repository.update_job(stored)
        await self.repository.add_attempt(
            JobAttemptRecord(
                id=f"attempt-{uuid4().hex[:20]}",
                job_id=stored.response.id,
                attempt=stored.response.attempt,
                slot_id=reservation.slot_id,
                gpu_id=reservation.gpu_id,
                runner_id=None,
                worker_pid=None,
                warm_start=None,
                status="assigned",
                error_code=None,
                created_at=utc_now(),
            )
        )
        await self._event(stored, "job.assigned")
        await self.dispatcher.dispatch(
            reservation,
            stored.response.id,
            {
                "job": stored.response.model_dump(mode="json", by_alias=True),
                "inputPaths": [str(path) if path else None for path in input_paths],
            },
        )
        if self.executor is not None:
            task = asyncio.create_task(self._execute(stored, reservation, input_paths))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

    async def _execute(
        self,
        stored: StoredJob,
        reservation: SlotReservation,
        input_paths: tuple[Path | None, Path | None],
    ) -> None:
        assert self.executor is not None
        try:
            result = await self.executor.execute(
                stored.response.id,
                stored.response.draft,
                self.artifacts.job_directory(stored.response.id),
                input_paths,
                lambda phase, progress, details: self._execution_event(
                    stored,
                    phase,
                    progress,
                    details,
                ),
                lambda: stored.response.id in self._cancel_requested,
            )
            if stored.response.id in self._cancel_requested:
                raise asyncio.CancelledError
            await self._succeed(stored, result)
        except asyncio.CancelledError:
            await self._update(stored, stage=JobStatus.CANCELLED, progress=stored.response.progress)
            await self._event(stored, "job.cancelled")
        except Exception as exc:
            code = str(exc).split(":", 1)[0] or "INFERENCE_FAILED"
            stored.response = stored.response.model_copy(
                update={
                    "stage": JobStatus.FAILED,
                    "updated_at": utc_now(),
                    "error": JobError(code=code, message=str(exc), retryable=True),
                }
            )
            await self.repository.update_job(stored)
            await self._event(stored, "job.failed")
        finally:
            self._reservations.pop(stored.response.id, None)
            await self.scheduler.release(reservation)

    async def _execution_event(
        self,
        stored: StoredJob,
        phase: str,
        progress: int,
        details: dict[str, object],
    ) -> None:
        stage = {
            "preparing": JobStatus.PREPARING,
            "prompt_encoding": JobStatus.PREPARING,
            "diffusion": JobStatus.GENERATING,
            "encoding": JobStatus.ENCODING,
        }.get(phase, JobStatus.GENERATING)
        stored.response = stored.response.model_copy(
            update={
                "stage": stage,
                "phase": phase,
                "progress": progress,
                "current_step": details.get("currentStep"),
                "total_steps": details.get("totalSteps"),
                "updated_at": utc_now(),
            }
        )
        await self.repository.update_job(stored)
        await self._event(stored, "job.updated")

    async def _succeed(self, stored: StoredJob, result: JobExecutionResult) -> None:
        asset = await self.artifacts.register_video(
            stored.owner_id,
            stored.response.id,
            result.output_path,
        )
        stored.output_path = result.output_path
        stored.manifest_path = result.manifest_path
        stored.response = stored.response.model_copy(
            update={
                "stage": JobStatus.SUCCEEDED,
                "progress": 100,
                "phase": "completed",
                "updated_at": utc_now(),
                "warm_start": result.warm_start,
                "output": JobOutput(
                    assetId=asset.id,
                    fileUrl=f"/v1/jobs/{stored.response.id}/file",
                    manifestUrl=f"/v1/jobs/{stored.response.id}/manifest",
                    sizeBytes=asset.size_bytes,
                ),
                "error": None,
            }
        )
        await self.repository.update_job(stored)
        await self._event(stored, "job.succeeded")

    async def _update(
        self,
        stored: StoredJob,
        *,
        stage: JobStatus,
        progress: int,
    ) -> None:
        stored.response = stored.response.model_copy(
            update={"stage": stage, "progress": progress, "updated_at": utc_now()}
        )
        await self.repository.update_job(stored)

    async def _event(self, stored: StoredJob, event_type: str) -> None:
        await self.repository.add_event(
            stored.owner_id,
            stored.response.id,
            event_type,
            stored.response.model_dump(mode="json", by_alias=True),
        )
        condition = self._conditions.setdefault(stored.response.id, asyncio.Condition())
        async with condition:
            condition.notify_all()

    async def _input_paths(
        self,
        owner_id: str,
        payload: JobCreate,
    ) -> tuple[Path | None, Path | None]:
        return await self._input_paths_from_draft(owner_id, payload.draft)

    async def _input_paths_from_draft(
        self,
        owner_id: str,
        draft,
    ) -> tuple[Path | None, Path | None]:
        paths: list[Path | None] = []
        for asset_id in (draft.first_frame_asset_id, draft.last_frame_asset_id):
            if asset_id is None:
                paths.append(None)
            else:
                asset = await self.repository.get_asset(owner_id, asset_id)
                if asset.response.type != "image":
                    raise ValueError("INVALID_ASSET")
                paths.append(asset.storage_path)
        return paths[0], paths[1]
