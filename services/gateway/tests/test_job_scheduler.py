import asyncio

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
    await sessions.close()


@pytest.mark.asyncio
async def test_four_ready_slots_run_four_jobs_without_double_assignment() -> None:
    inventory = GpuInventoryService(
        InMemoryInventoryProvider(
            [
                GpuInfo(
                    id=f"GPU-capacity-{index}",
                    physicalIndex=index,
                    name="H100",
                    vramTotalMiB=81_559,
                    state=GpuState.EMPTY,
                    eligible=True,
                )
                for index in (0, 2, 5, 7)
            ]
        )
    )
    sessions = ComputeSessionService(inventory, RecordingComputeBackend())
    session = await sessions.create("owner", ComputeSessionCreate(requestedGpuCount=4))
    scheduler = JobScheduler(sessions)

    reservations = await asyncio.gather(
        scheduler.reserve("owner", session.id, ProfileTier.FAST),
        scheduler.reserve("owner", session.id, ProfileTier.FAST),
        scheduler.reserve("owner", session.id, ProfileTier.HQ),
        scheduler.reserve("owner", session.id, ProfileTier.HQ),
    )

    assert len({item.slot_id for item in reservations}) == 4
    assert len({item.gpu_id for item in reservations}) == 4
    with pytest.raises(RuntimeError, match="COMPUTE_NOT_READY"):
        await scheduler.reserve("owner", session.id, ProfileTier.FAST)
    for reservation in reservations:
        await scheduler.release(reservation)
    await sessions.close()
