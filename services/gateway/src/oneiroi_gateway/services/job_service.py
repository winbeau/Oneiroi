import asyncio
from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from oneiroi_common.compute import FAST_PROFILE_ID, HQ_PROFILE_ID, ProfileTier
from oneiroi_common.errors import ErrorCode, OneiroiError
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
from oneiroi_gateway.services.job_execution import (
    JobExecutionContext,
    JobExecutionResult,
    JobExecutor,
)
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
        max_active_per_owner: int = 4,
    ) -> None:
        self.repository = repository
        self.sessions = sessions
        self.capabilities = capabilities
        self.scheduler = scheduler
        self.dispatcher = dispatcher
        self.artifacts = artifacts
        self.executor = executor
        self.max_active_per_owner = max_active_per_owner
        self._conditions: dict[str, asyncio.Condition] = {}
        self._cancel_requested: set[str] = set()
        self._reservations: dict[str, SlotReservation] = {}
        self._tasks: set[asyncio.Task[None]] = set()
        self._shutting_down = False

    async def close(self) -> None:
        self._shutting_down = True
        tasks = list(self._tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def create(self, owner_id: str, payload: JobCreate) -> JobResponse:
        await self.repository.get_conversation(owner_id, payload.conversation_id)
        # One conversation is locked to a single active job at a time.
        active_in_conversation = await self.repository.count_active_jobs(
            owner_id, conversation_id=payload.conversation_id
        )
        if active_in_conversation > 0:
            raise OneiroiError(
                ErrorCode.CONVERSATION_BUSY,
                "当前会话已有任务在生成，请等待完成后重试",
            )
        # An account may run at most max_active_per_owner jobs concurrently.
        active_total = await self.repository.count_active_jobs(owner_id)
        if active_total >= self.max_active_per_owner:
            raise OneiroiError(
                ErrorCode.CONCURRENCY_LIMIT,
                f"账户并发任务已达上限（{self.max_active_per_owner} 个），请等待任一任务完成后重试",
            )
        session = self.sessions.get(owner_id, payload.compute_session_id)
        self.capabilities.require_profile(session, payload.draft.profile)
        input_paths = await self._input_paths(owner_id, payload)
        now = utc_now()
        profile_id = HQ_PROFILE_ID if payload.draft.profile is ProfileTier.HQ else FAST_PROFILE_ID
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
        try:
            await self._assign_and_dispatch(stored, input_paths)
        except Exception as exc:
            await self._mark_dispatch_failed(stored, exc)
            raise
        return stored.response.model_copy(deep=True)

    async def restore_inflight(self) -> list[str]:
        if self.executor is None:
            return []
        restored: list[str] = []
        for stored in await self.repository.list_incomplete_jobs():
            try:
                session = self.sessions.get(
                    stored.owner_id,
                    stored.response.compute_session_id,
                )
                if stored.response.gpu is None:
                    raise RuntimeError("JOB_HAS_NO_GPU_ASSIGNMENT")
                slot = next(item for item in session.slots if item.gpu_id == stored.response.gpu.id)
                reservation = SlotReservation(
                    session_id=session.id,
                    slot_id=slot.id,
                    gpu_id=slot.gpu_id,
                    physical_index=slot.physical_index,
                    profile=stored.response.draft.profile,
                    fencing_token=self.sessions.fencing_token(slot.id),
                )
                await self.scheduler.restore(reservation)
                self._reservations[stored.response.id] = reservation
                if stored.response.stage is JobStatus.CANCEL_REQUESTED:
                    self._cancel_requested.add(stored.response.id)
                input_paths = await self._input_paths_from_draft(
                    stored.owner_id,
                    stored.response.draft,
                )
                task = asyncio.create_task(
                    self._execute(stored, reservation, input_paths),
                    name=f"restore-{stored.response.id}",
                )
                self._tasks.add(task)
                task.add_done_callback(self._tasks.discard)
                restored.append(stored.response.id)
            except Exception as exc:
                await self._mark_dispatch_failed(stored, exc)
        return restored

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
            await self._finish_attempt(stored, "cancelled")
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
        try:
            await self._assign_and_dispatch(stored, input_paths)
        except Exception as exc:
            await self._mark_dispatch_failed(stored, exc)
            raise
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
        try:
            await self.dispatcher.dispatch(
                reservation,
                stored.response.id,
                {
                    "job": stored.response.model_dump(mode="json", by_alias=True),
                    "inputPaths": [str(path) if path else None for path in input_paths],
                },
            )
        except Exception:
            self._reservations.pop(stored.response.id, None)
            await self.scheduler.release(reservation)
            raise
        if self.executor is not None:
            task = asyncio.create_task(self._execute(stored, reservation, input_paths))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

    async def _mark_dispatch_failed(self, stored: StoredJob, exc: Exception) -> None:
        if stored.response.stage.is_terminal:
            return
        stored.response = stored.response.model_copy(
            update={
                "stage": JobStatus.FAILED,
                "updated_at": utc_now(),
                "error": JobError(
                    code="DISPATCH_FAILED",
                    message=str(exc),
                    retryable=True,
                ),
            }
        )
        await self.repository.update_job(stored)
        await self._event(stored, "job.failed")
        await self._finish_attempt(stored, "failed", error_code="DISPATCH_FAILED")

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
                JobExecutionContext(
                    session_id=reservation.session_id,
                    attempt=stored.response.attempt,
                ),
            )
            await self._succeed(stored, result)
        except asyncio.CancelledError:
            if self._shutting_down:
                return
            await self._update(stored, stage=JobStatus.CANCELLED, progress=stored.response.progress)
            await self._event(stored, "job.cancelled")
            await self._finish_attempt(stored, "cancelled")
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
            await self._finish_attempt(stored, "failed", error_code=code)
        finally:
            if not self._shutting_down:
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
            "model-loading": JobStatus.LOADING_MODEL,
            "prompt_encoding": JobStatus.PREPARING,
            "prompt-encoding": JobStatus.PREPARING,
            "conditioning": JobStatus.PREPARING,
            "diffusion": JobStatus.GENERATING,
            "stage-1": JobStatus.GENERATING,
            "upsampling": JobStatus.GENERATING,
            "stage-2": JobStatus.GENERATING,
            "decoding": JobStatus.ENCODING,
            "encoding": JobStatus.ENCODING,
            "uploading": JobStatus.ENCODING,
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
        await self._finish_attempt(
            stored,
            "succeeded",
            warm_start=result.warm_start,
            worker_pid=(
                int(result.metrics["workerPid"])
                if result.metrics.get("workerPid") is not None
                else None
            ),
            peak_vram_mib=(
                int(result.metrics["peakVramMiB"])
                if result.metrics.get("peakVramMiB") is not None
                else None
            ),
            generation_seconds=(
                float(result.metrics["elapsedSeconds"])
                if result.metrics.get("elapsedSeconds") is not None
                else None
            ),
        )

    async def _finish_attempt(
        self,
        stored: StoredJob,
        status: str,
        *,
        error_code: str | None = None,
        warm_start: bool | None = None,
        worker_pid: int | None = None,
        peak_vram_mib: int | None = None,
        generation_seconds: float | None = None,
    ) -> None:
        attempts = await self.repository.list_attempts(stored.response.id)
        current = next(
            (item for item in attempts if item.attempt == stored.response.attempt),
            None,
        )
        if current is None:
            return
        await self.repository.update_attempt(
            replace(
                current,
                status=status,
                error_code=error_code,
                warm_start=warm_start,
                worker_pid=worker_pid,
                peak_vram_mib=peak_vram_mib,
                generation_seconds=generation_seconds,
                finished_at=utc_now(),
            )
        )

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
