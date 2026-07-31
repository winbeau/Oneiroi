import asyncio

import pytest

from oneiroi_common.compute import GpuState
from oneiroi_runner.heartbeat import InMemoryHeartbeatPublisher, heartbeat_loop
from oneiroi_runner.state import RunnerState


@pytest.mark.asyncio
async def test_heartbeat_carries_uuid_and_slot_state() -> None:
    state = RunnerState(
        runner_id="runner-a",
        slot_id="slot-a",
        gpu_id="GPU-aaaa",
        physical_index=7,
        vram_total_mib=81_559,
        state=GpuState.EMPTY,
    )
    publisher = InMemoryHeartbeatPublisher()
    stop = asyncio.Event()

    async def factory():
        stop.set()
        return state.heartbeat()

    await heartbeat_loop(publisher, factory, interval_seconds=1, stop_event=stop)

    assert publisher.items[0].gpu_id == "GPU-aaaa"
    assert publisher.items[0].physical_index == 7
    assert publisher.items[0].state == "empty"
