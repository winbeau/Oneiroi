from pathlib import Path

from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from oneiroi_common.jobs import JobStatus
from oneiroi_common.studio import AssetResponse, ConversationResponse, JobEventResponse, JobResponse
from oneiroi_gateway.db.models.studio import (
    AssetModel,
    ConversationModel,
    JobAttemptModel,
    JobEventModel,
    JobModel,
)
from oneiroi_gateway.repositories.studio import JobAttemptRecord, StoredAsset, StoredJob, utc_now


class SqlStudioRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions

    async def create_conversation(self, owner_id: str, title: str) -> ConversationResponse:
        from uuid import uuid4

        now = utc_now()
        response = ConversationResponse(
            id=f"conversation-{uuid4().hex[:16]}",
            title=title,
            createdAt=now,
            updatedAt=now,
        )
        async with self.sessions() as session:
            session.add(
                ConversationModel(
                    id=response.id,
                    owner_id=owner_id,
                    title=title,
                    created_at=now,
                    updated_at=now,
                )
            )
            await session.commit()
        return response

    async def list_conversations(self, owner_id: str) -> list[ConversationResponse]:
        async with self.sessions() as session:
            rows = (
                await session.scalars(
                    select(ConversationModel)
                    .where(ConversationModel.owner_id == owner_id)
                    .order_by(ConversationModel.updated_at.desc())
                )
            ).all()
        return [self._conversation(row) for row in rows]

    async def get_conversation(self, owner_id: str, conversation_id: str) -> ConversationResponse:
        async with self.sessions() as session:
            row = await session.scalar(
                select(ConversationModel).where(
                    ConversationModel.id == conversation_id,
                    ConversationModel.owner_id == owner_id,
                )
            )
        if row is None:
            raise KeyError(conversation_id)
        return self._conversation(row)

    async def put_conversation(
        self,
        owner_id: str,
        conversation_id: str,
        title: str,
    ) -> ConversationResponse:
        async with self.sessions() as session:
            row = await session.scalar(
                select(ConversationModel).where(
                    ConversationModel.id == conversation_id,
                    ConversationModel.owner_id == owner_id,
                )
            )
            if row is None:
                raise KeyError(conversation_id)
            row.title = title
            row.updated_at = utc_now()
            await session.commit()
            await session.refresh(row)
        return self._conversation(row)

    async def delete_conversation(self, owner_id: str, conversation_id: str) -> None:
        async with self.sessions() as session:
            conversation = await session.scalar(
                select(ConversationModel).where(
                    ConversationModel.id == conversation_id,
                    ConversationModel.owner_id == owner_id,
                )
            )
            if conversation is None:
                raise KeyError(conversation_id)
            job_ids = list(
                (await session.scalars(
                    select(JobModel.id).where(
                        JobModel.conversation_id == conversation_id,
                        JobModel.owner_id == owner_id,
                    )
                )).all()
            )
            if job_ids:
                await session.execute(
                    delete(JobAttemptModel).where(JobAttemptModel.job_id.in_(job_ids))
                )
                await session.execute(
                    delete(JobEventModel).where(JobEventModel.job_id.in_(job_ids))
                )
                await session.execute(delete(JobModel).where(JobModel.id.in_(job_ids)))
                # Best-effort cleanup of gpu-server records in the shared database.
                await session.execute(
                    text("DELETE FROM gpu_server_job_events WHERE stream_id = ANY(:ids)"),
                    {"ids": job_ids},
                )
                await session.execute(
                    text("DELETE FROM gpu_server_jobs WHERE external_job_id = ANY(:ids)"),
                    {"ids": job_ids},
                )
            await session.execute(
                delete(ConversationModel).where(
                    ConversationModel.id == conversation_id,
                    ConversationModel.owner_id == owner_id,
                )
            )
            await session.commit()

    async def list_jobs_for_conversation(
        self,
        owner_id: str,
        conversation_id: str,
    ) -> list[StoredJob]:
        async with self.sessions() as session:
            rows = (
                await session.scalars(
                    select(JobModel).where(
                        JobModel.conversation_id == conversation_id,
                        JobModel.owner_id == owner_id,
                    )
                )
            ).all()
        return [self._stored_job(row) for row in rows]

    async def create_asset(self, asset: StoredAsset) -> AssetResponse:
        response = asset.response
        async with self.sessions() as session:
            session.add(
                AssetModel(
                    id=response.id,
                    owner_id=asset.owner_id,
                    type=response.type,
                    title=response.title,
                    media_type=response.media_type,
                    size_bytes=response.size_bytes,
                    width=response.width,
                    height=response.height,
                    source_job_id=response.source_job_id,
                    storage_path=str(asset.storage_path),
                    sha256=asset.sha256,
                    response_json=response.model_dump(mode="json", by_alias=True),
                    created_at=response.created_at,
                )
            )
            await session.commit()
        return response

    async def list_assets(self, owner_id: str) -> list[AssetResponse]:
        async with self.sessions() as session:
            rows = (
                await session.scalars(
                    select(AssetModel)
                    .where(AssetModel.owner_id == owner_id)
                    .order_by(AssetModel.created_at.desc())
                )
            ).all()
        return [AssetResponse.model_validate(row.response_json) for row in rows]

    async def get_asset(self, owner_id: str, asset_id: str) -> StoredAsset:
        async with self.sessions() as session:
            row = await session.scalar(
                select(AssetModel).where(
                    AssetModel.id == asset_id,
                    AssetModel.owner_id == owner_id,
                )
            )
        if row is None:
            raise KeyError(asset_id)
        return StoredAsset(
            owner_id=row.owner_id,
            response=AssetResponse.model_validate(row.response_json),
            storage_path=Path(row.storage_path),
            sha256=row.sha256,
        )

    async def delete_asset(self, owner_id: str, asset_id: str) -> None:
        async with self.sessions() as session:
            result = await session.execute(
                delete(AssetModel).where(
                    AssetModel.id == asset_id,
                    AssetModel.owner_id == owner_id,
                )
            )
            if result.rowcount == 0:
                raise KeyError(asset_id)
            await session.commit()

    async def create_job(self, job: StoredJob) -> JobResponse:
        response = job.response
        async with self.sessions() as session:
            session.add(self._job_model(job))
            await session.commit()
        return response

    async def list_jobs(self, owner_id: str) -> list[JobResponse]:
        async with self.sessions() as session:
            rows = (
                await session.scalars(
                    select(JobModel)
                    .where(JobModel.owner_id == owner_id)
                    .order_by(JobModel.created_at.desc())
                )
            ).all()
        return [JobResponse.model_validate(row.response_json) for row in rows]

    async def list_incomplete_jobs(self) -> list[StoredJob]:
        terminal = [
            JobStatus.SUCCEEDED.value,
            JobStatus.FAILED.value,
            JobStatus.CANCELLED.value,
        ]
        async with self.sessions() as session:
            rows = (
                await session.scalars(select(JobModel).where(JobModel.state.not_in(terminal)))
            ).all()
        return [self._stored_job(row) for row in rows]

    async def count_active_jobs(
        self, owner_id: str, conversation_id: str | None = None
    ) -> int:
        terminal = [
            JobStatus.SUCCEEDED.value,
            JobStatus.FAILED.value,
            JobStatus.CANCELLED.value,
        ]
        async with self.sessions() as session:
            query = select(func.count()).select_from(JobModel).where(
                JobModel.owner_id == owner_id,
                JobModel.state.not_in(terminal),
            )
            if conversation_id is not None:
                query = query.where(JobModel.conversation_id == conversation_id)
            return int((await session.scalar(query)) or 0)

    async def get_job(self, owner_id: str, job_id: str) -> StoredJob:
        async with self.sessions() as session:
            row = await session.scalar(
                select(JobModel).where(JobModel.id == job_id, JobModel.owner_id == owner_id)
            )
        if row is None:
            raise KeyError(job_id)
        return self._stored_job(row)

    async def update_job(self, job: StoredJob) -> JobResponse:
        async with self.sessions() as session:
            row = await session.scalar(select(JobModel).where(JobModel.id == job.response.id))
            if row is None:
                raise KeyError(job.response.id)
            response = job.response
            row.state = response.stage.value
            row.progress = response.progress
            row.current_attempt = response.attempt
            row.profile_id = response.profile_id
            row.result_asset_id = response.output.asset_id if response.output else None
            row.error_code = response.error.code if response.error else None
            row.response_json = response.model_dump(mode="json", by_alias=True)
            row.manifest_path = str(job.manifest_path) if job.manifest_path else None
            row.output_path = str(job.output_path) if job.output_path else None
            row.updated_at = response.updated_at
            await session.commit()
        return response

    async def add_attempt(self, attempt: JobAttemptRecord) -> None:
        async with self.sessions() as session:
            session.add(
                JobAttemptModel(
                    id=attempt.id,
                    job_id=attempt.job_id,
                    attempt=attempt.attempt,
                    slot_id=attempt.slot_id,
                    gpu_uuid=attempt.gpu_id,
                    runner_id=attempt.runner_id,
                    worker_pid=attempt.worker_pid,
                    warm_start=attempt.warm_start,
                    status=attempt.status,
                    error_code=attempt.error_code,
                    peak_vram_mib=attempt.peak_vram_mib,
                    load_seconds=attempt.load_seconds,
                    generation_seconds=attempt.generation_seconds,
                    encoding_seconds=attempt.encoding_seconds,
                    created_at=attempt.created_at,
                    finished_at=attempt.finished_at,
                )
            )
            await session.commit()

    async def update_attempt(self, attempt: JobAttemptRecord) -> None:
        async with self.sessions() as session:
            row = await session.get(JobAttemptModel, attempt.id)
            if row is None:
                raise KeyError(attempt.id)
            row.runner_id = attempt.runner_id
            row.worker_pid = attempt.worker_pid
            row.warm_start = attempt.warm_start
            row.status = attempt.status
            row.error_code = attempt.error_code
            row.peak_vram_mib = attempt.peak_vram_mib
            row.load_seconds = attempt.load_seconds
            row.generation_seconds = attempt.generation_seconds
            row.encoding_seconds = attempt.encoding_seconds
            row.finished_at = attempt.finished_at
            await session.commit()

    async def list_attempts(self, job_id: str) -> list[JobAttemptRecord]:
        async with self.sessions() as session:
            rows = (
                await session.scalars(
                    select(JobAttemptModel)
                    .where(JobAttemptModel.job_id == job_id)
                    .order_by(JobAttemptModel.attempt)
                )
            ).all()
        return [
            JobAttemptRecord(
                id=row.id,
                job_id=row.job_id,
                attempt=row.attempt,
                slot_id=row.slot_id,
                gpu_id=row.gpu_uuid,
                runner_id=row.runner_id,
                worker_pid=row.worker_pid,
                warm_start=row.warm_start,
                status=row.status,
                error_code=row.error_code,
                created_at=row.created_at,
                finished_at=row.finished_at,
                peak_vram_mib=row.peak_vram_mib,
                load_seconds=row.load_seconds,
                generation_seconds=row.generation_seconds,
                encoding_seconds=row.encoding_seconds,
            )
            for row in rows
        ]

    async def add_event(
        self,
        owner_id: str,
        job_id: str,
        event_type: str,
        payload: dict[str, object],
    ) -> JobEventResponse:
        await self.get_job(owner_id, job_id)
        now = utc_now()
        async with self.sessions() as session:
            row = JobEventModel(
                owner_id=owner_id,
                job_id=job_id,
                event_type=event_type,
                payload_json=payload,
                created_at=now,
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)
        return JobEventResponse(
            id=row.id,
            jobId=job_id,
            eventType=event_type,
            payload=payload,
            createdAt=now,
        )

    async def list_events(
        self,
        owner_id: str,
        job_id: str,
        after_id: int = 0,
    ) -> list[JobEventResponse]:
        await self.get_job(owner_id, job_id)
        async with self.sessions() as session:
            rows = (
                await session.scalars(
                    select(JobEventModel)
                    .where(JobEventModel.job_id == job_id, JobEventModel.id > after_id)
                    .order_by(JobEventModel.id)
                )
            ).all()
        return [
            JobEventResponse(
                id=row.id,
                jobId=row.job_id,
                eventType=row.event_type,
                payload=row.payload_json,
                createdAt=row.created_at,
            )
            for row in rows
        ]

    @staticmethod
    def _conversation(row: ConversationModel) -> ConversationResponse:
        return ConversationResponse(
            id=row.id,
            title=row.title,
            createdAt=row.created_at,
            updatedAt=row.updated_at,
        )

    @staticmethod
    def _job_model(job: StoredJob) -> JobModel:
        response = job.response
        return JobModel(
            id=response.id,
            owner_id=job.owner_id,
            conversation_id=response.conversation_id,
            compute_session_id=response.compute_session_id,
            state=response.stage.value,
            progress=response.progress,
            current_attempt=response.attempt,
            profile_id=response.profile_id,
            result_asset_id=response.output.asset_id if response.output else None,
            error_code=response.error.code if response.error else None,
            request_json=response.draft.model_dump(mode="json", by_alias=True),
            response_json=response.model_dump(mode="json", by_alias=True),
            manifest_path=str(job.manifest_path) if job.manifest_path else None,
            output_path=str(job.output_path) if job.output_path else None,
            created_at=response.created_at,
            updated_at=response.updated_at,
        )

    @staticmethod
    def _stored_job(row: JobModel) -> StoredJob:
        return StoredJob(
            owner_id=row.owner_id,
            response=JobResponse.model_validate(row.response_json),
            manifest_path=Path(row.manifest_path) if row.manifest_path else None,
            output_path=Path(row.output_path) if row.output_path else None,
        )
