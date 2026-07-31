from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from oneiroi_common.compute import GpuInfo, GpuInventoryResponse, GpuState


class InventoryProvider(Protocol):
    async def list_gpus(self) -> list[GpuInfo]: ...


class InMemoryInventoryProvider:
    def __init__(self, gpus: Iterable[GpuInfo] = ()) -> None:
        self.gpus = list(gpus)

    async def list_gpus(self) -> list[GpuInfo]:
        return [gpu.model_copy(deep=True) for gpu in self.gpus]


@dataclass(slots=True)
class NvmlInventoryProvider:
    allowlist: frozenset[str] | None = None
    minimum_vram_mib: int = 70_000
    idle_vram_threshold_mib: int = 2_048

    async def list_gpus(self) -> list[GpuInfo]:
        try:
            import pynvml
        except ImportError as exc:
            raise RuntimeError("nvidia-ml-py is required when NVML inventory is enabled") from exc

        pynvml.nvmlInit()
        try:
            result: list[GpuInfo] = []
            now = datetime.now(UTC).isoformat()
            for index in range(pynvml.nvmlDeviceGetCount()):
                handle = pynvml.nvmlDeviceGetHandleByIndex(index)
                uuid = _decode(pynvml.nvmlDeviceGetUUID(handle))
                name = _decode(pynvml.nvmlDeviceGetName(handle))
                memory = pynvml.nvmlDeviceGetMemoryInfo(handle)
                utilization = pynvml.nvmlDeviceGetUtilizationRates(handle)
                try:
                    processes = pynvml.nvmlDeviceGetComputeRunningProcesses(handle)
                except pynvml.NVMLError:
                    processes = []

                total_mib = memory.total // (1024 * 1024)
                used_mib = memory.used // (1024 * 1024)
                state = GpuState.EMPTY
                reason: str | None = None
                if self.allowlist is not None and uuid not in self.allowlist:
                    reason = "GPU_NOT_ALLOWED"
                elif processes:
                    state = GpuState.FOREIGN_BUSY
                    reason = "EXTERNAL_COMPUTE_PROCESS"
                elif total_mib < self.minimum_vram_mib:
                    reason = "INSUFFICIENT_VRAM"
                elif used_mib >= self.idle_vram_threshold_mib:
                    reason = "VRAM_ABOVE_IDLE_THRESHOLD"

                result.append(
                    GpuInfo(
                        id=uuid,
                        physical_index=index,
                        name=name,
                        vram_total_mib=total_mib,
                        vram_used_mib=used_mib,
                        utilization_percent=float(utilization.gpu),
                        temperature_celsius=float(
                            pynvml.nvmlDeviceGetTemperature(
                                handle,
                                pynvml.NVML_TEMPERATURE_GPU,
                            )
                        ),
                        state=state,
                        eligible=reason is None,
                        unavailable_reason=reason,
                        external_process_count=len(processes),
                        last_heartbeat_at=now,
                    )
                )
            return result
        finally:
            pynvml.nvmlShutdown()


def _decode(value: str | bytes) -> str:
    return value.decode() if isinstance(value, bytes) else value


class GpuInventoryService:
    def __init__(self, provider: InventoryProvider) -> None:
        self.provider = provider

    async def snapshot(self) -> GpuInventoryResponse:
        gpus = await self.provider.list_gpus()
        return GpuInventoryResponse(gpus=sorted(gpus, key=lambda gpu: gpu.physical_index))
