import pytest

from oneiroi_common.compute import ComputeSessionCreate, GpuInfo, GpuState, ProfileTier
from oneiroi_gateway.services.compute_sessions import ComputeSessionService, RecordingComputeBackend
from oneiroi_gateway.services.gpu_inventory import GpuInventoryService, InMemoryInventoryProvider
from oneiroi_gateway.services.job_scheduler import JobScheduler


@pytest.mark.asyncio
async def test_ready_slot_allows_only_one_job_at_a_time() -> None:
    inventory = GpuInventoryService(
        InMemoryInventoryProvider(
            [
                GpuInfo(
                    id="GPU-one",
                    physicalIndex=0,
                    name="H100",
                    vramTotalMiB=81_559,
                    state=GpuState.EMPTY,
                    eligible=True,
                )
            ]
        )
    )
    sessions = ComputeSessionService(inventory, RecordingComputeBackend())
    session = await sessions.create("owner", ComputeSessionCreate(requestedGpuCount=1))
    scheduler = JobScheduler(sessions)

    reservation = await scheduler.reserve("owner", session.id, ProfileTier.FAST)
    with pytest.raises(RuntimeError, match="COMPUTE_NOT_READY"):
        await scheduler.reserve("owner", session.id, ProfileTier.FAST)
    await scheduler.release(reservation)
    second = await scheduler.reserve("owner", session.id, ProfileTier.FAST)

    assert second.slot_id == reservation.slot_id
