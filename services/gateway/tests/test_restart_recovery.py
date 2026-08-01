import asyncio
from pathlib import Path

import pytest

from oneiroi_common.compute import ComputeSessionCreate, GpuInfo, GpuState
from oneiroi_common.studio import GenerationDraft, JobCreate
from oneiroi_gateway.redis.leases import InMemoryLeaseStore
from oneiroi_gateway.repositories.compute import InMemoryComputeStateRepository
from oneiroi_gateway.repositories.studio import InMemoryStudioRepository
from oneiroi_gateway.services.artifact_service import ArtifactService
from oneiroi_gateway.services.capabilities import CapabilityService
from oneiroi_gateway.services.compute_sessions import ComputeSessionService, RecordingComputeBackend
from oneiroi_gateway.services.gpu_inventory import GpuInventoryService, InMemoryInventoryProvider
from oneiroi_gateway.services.job_dispatcher import InMemoryJobDispatcher
from oneiroi_gateway.services.job_execution import FakeJobExecutor
from oneiroi_gateway.services.job_scheduler import JobScheduler
from oneiroi_gateway.services.job_service import JobService


class BlockingExecutor:
    def __init__(self) -> None:
        self.started = asyncio.Event()

    async def execute(self, *args, **kwargs):
        del args, kwargs
        self.started.set()
        await asyncio.Event().wait()
        raise AssertionError("unreachable")


def inventory() -> GpuInventoryService:
    return GpuInventoryService(
        InMemoryInventoryProvider(
            [
                GpuInfo(
                    id="GPU-restart",
                    physicalIndex=7,
                    name="H100",
                    vramTotalMiB=81_559,
                    state=GpuState.EMPTY,
                    eligible=True,
                )
            ]
        )
    )


def job_service(
    repository,
    sessions,
    artifacts,
    executor,
) -> JobService:
    return JobService(
        repository,
        sessions,
        CapabilityService(),
        JobScheduler(sessions),
        InMemoryJobDispatcher(),
        artifacts,
        executor,
    )


@pytest.mark.asyncio
async def test_gateway_restart_recovers_active_session_and_inflight_job(tmp_path: Path) -> None:
    repository = InMemoryStudioRepository()
    state_repository = InMemoryComputeStateRepository()
    leases = InMemoryLeaseStore()
    artifacts = ArtifactService(repository, tmp_path, max_upload_bytes=1024)
    first_sessions = ComputeSessionService(
        inventory(),
        RecordingComputeBackend(),
        leases=leases,
        state_repository=state_repository,
    )
    conversation = await repository.create_conversation("owner", "Restart")
    compute = await first_sessions.create(
        "owner",
        ComputeSessionCreate(requestedGpuCount=1),
    )
    blocking = BlockingExecutor()
    first_jobs = job_service(repository, first_sessions, artifacts, blocking)
    created = await first_jobs.create(
        "owner",
        JobCreate(
            conversationId=conversation.id,
            computeSessionId=compute.id,
            draft=GenerationDraft(prompt="recover after restart"),
        ),
    )
    await asyncio.wait_for(blocking.started.wait(), timeout=1)
    await first_jobs.close()
    await first_sessions.close()

    second_sessions = ComputeSessionService(
        inventory(),
        RecordingComputeBackend(),
        leases=leases,
        state_repository=state_repository,
    )
    assert await second_sessions.restore() == [compute.id]
    second_jobs = job_service(repository, second_sessions, artifacts, FakeJobExecutor())
    assert await second_jobs.restore_inflight() == [created.id]

    for _ in range(100):
        restored = await repository.get_job("owner", created.id)
        if restored.response.stage.is_terminal:
            break
        await asyncio.sleep(0.02)

    assert restored.response.stage.value == "succeeded"
    assert restored.output_path is not None and restored.output_path.is_file()
    await second_jobs.close()
    await second_sessions.close()
