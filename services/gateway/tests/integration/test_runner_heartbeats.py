import asyncio
import os
from uuid import uuid4

import pytest

from oneiroi_common.compute import ComputeSessionCreate, GpuInfo, GpuState
from oneiroi_gateway.redis.leases import InMemoryLeaseStore
from oneiroi_gateway.services.compute_sessions import ComputeSessionService, RecordingComputeBackend
from oneiroi_gateway.services.gpu_inventory import GpuInventoryService, InMemoryInventoryProvider
from oneiroi_gateway.services.runner_heartbeats import RunnerHeartbeatMonitor

pytestmark = pytest.mark.skipif(
    os.getenv("ONEIROI_TEST_REDIS") != "1",
    reason="set ONEIROI_TEST_REDIS=1 for the loopback Redis integration test",
)


@pytest.mark.asyncio
async def test_missing_runner_heartbeat_marks_slot_failed_and_releases_lease() -> None:
    suffix = uuid4().hex
    gpu_id = f"GPU-heartbeat-{suffix}"
    inventory = GpuInventoryService(
        InMemoryInventoryProvider(
            [
                GpuInfo(
                    id=gpu_id,
                    physicalIndex=7,
                    name="H100",
                    vramTotalMiB=81_559,
                    state=GpuState.EMPTY,
                    eligible=True,
                )
            ]
        )
    )
    leases = InMemoryLeaseStore()
    sessions = ComputeSessionService(
        inventory,
        RecordingComputeBackend(),
        leases=leases,
    )
    session = await sessions.create("owner", ComputeSessionCreate(requestedGpuCount=1))
    monitor = RunnerHeartbeatMonitor(
        os.getenv("ONEIROI_GATEWAY_REDIS_URL", "redis://127.0.0.1:6379/0"),
        sessions,
        timeout_seconds=0.05,
    )
    stop_event = asyncio.Event()
    task = asyncio.create_task(monitor.run(stop_event))
    try:
        for _ in range(30):
            if session.error_code == "RUNNER_HEARTBEAT_LOST":
                break
            await asyncio.sleep(0.01)

        assert session.error_code == "RUNNER_HEARTBEAT_LOST"
        assert session.slots[0].state is GpuState.ERROR
        assert await leases.active() == {}
    finally:
        await monitor.stop(task, stop_event)
        await sessions.close()
