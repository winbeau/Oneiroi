from dataclasses import dataclass
from datetime import UTC, datetime

from oneiroi_common.compute import GpuState
from oneiroi_common.runner_protocol import RunnerHeartbeat


@dataclass(slots=True)
class RunnerState:
    runner_id: str
    slot_id: str
    gpu_id: str
    physical_index: int
    vram_total_mib: int
    vram_used_mib: int = 0
    state: GpuState = GpuState.EMPTY
    worker_pid: int | None = None

    def heartbeat(self) -> RunnerHeartbeat:
        return RunnerHeartbeat(
            runner_id=self.runner_id,
            slot_id=self.slot_id,
            gpu_id=self.gpu_id,
            physical_index=self.physical_index,
            state=self.state.value,
            vram_used_mib=self.vram_used_mib,
            vram_total_mib=self.vram_total_mib,
            worker_pid=self.worker_pid,
            occurred_at=datetime.now(UTC).isoformat(),
        )
