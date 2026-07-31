from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from oneiroi_common.compute import GpuInfo, GpuState


@dataclass(frozen=True, slots=True)
class GpuTelemetrySample:
    uuid: str
    physical_index: int
    name: str
    vram_total_mib: int
    vram_used_mib: int
    utilization_percent: float
    temperature_celsius: float
    compute_process_pids: tuple[int, ...] = ()
    hardware_error: str | None = None


@dataclass(frozen=True, slots=True)
class InventoryPolicy:
    allowlist: frozenset[str] | None = None
    minimum_vram_mib: int = 70_000
    idle_vram_threshold_mib: int = 2_048


class TelemetryProvider(Protocol):
    def collect(self) -> list[GpuTelemetrySample]: ...


class FakeTelemetryProvider:
    def __init__(self, samples: Iterable[GpuTelemetrySample]) -> None:
        self.samples = list(samples)

    def collect(self) -> list[GpuTelemetrySample]:
        return list(self.samples)


class NvmlTelemetryProvider:
    def collect(self) -> list[GpuTelemetrySample]:
        try:
            import pynvml
        except ImportError as exc:
            raise RuntimeError("nvidia-ml-py is required for NVML telemetry") from exc

        pynvml.nvmlInit()
        try:
            samples: list[GpuTelemetrySample] = []
            for index in range(pynvml.nvmlDeviceGetCount()):
                handle = pynvml.nvmlDeviceGetHandleByIndex(index)
                memory = pynvml.nvmlDeviceGetMemoryInfo(handle)
                utilization = pynvml.nvmlDeviceGetUtilizationRates(handle)
                uuid = _decode(pynvml.nvmlDeviceGetUUID(handle))
                name = _decode(pynvml.nvmlDeviceGetName(handle))
                try:
                    processes = pynvml.nvmlDeviceGetComputeRunningProcesses(handle)
                except pynvml.NVMLError:
                    processes = []
                samples.append(
                    GpuTelemetrySample(
                        uuid=uuid,
                        physical_index=index,
                        name=name,
                        vram_total_mib=memory.total // (1024 * 1024),
                        vram_used_mib=memory.used // (1024 * 1024),
                        utilization_percent=float(utilization.gpu),
                        temperature_celsius=float(
                            pynvml.nvmlDeviceGetTemperature(
                                handle,
                                pynvml.NVML_TEMPERATURE_GPU,
                            )
                        ),
                        compute_process_pids=tuple(process.pid for process in processes),
                    )
                )
            return samples
        finally:
            pynvml.nvmlShutdown()


def _decode(value: str | bytes) -> str:
    return value.decode() if isinstance(value, bytes) else value


def classify_gpu(
    sample: GpuTelemetrySample,
    policy: InventoryPolicy,
    *,
    leased: bool = False,
    oneiroi_worker_pids: frozenset[int] = frozenset(),
) -> GpuInfo:
    external_pids = tuple(
        pid for pid in sample.compute_process_pids if pid not in oneiroi_worker_pids
    )
    reason: str | None = None
    state = GpuState.EMPTY

    if policy.allowlist is not None and sample.uuid not in policy.allowlist:
        reason = "GPU_NOT_ALLOWED"
    elif sample.hardware_error:
        state = GpuState.ERROR
        reason = sample.hardware_error
    elif leased:
        state = GpuState.RESERVED
        reason = "GPU_LEASED"
    elif external_pids:
        state = GpuState.FOREIGN_BUSY
        reason = "EXTERNAL_COMPUTE_PROCESS"
    elif sample.vram_total_mib < policy.minimum_vram_mib:
        reason = "INSUFFICIENT_VRAM"
    elif sample.vram_used_mib >= policy.idle_vram_threshold_mib:
        reason = "VRAM_ABOVE_IDLE_THRESHOLD"

    return GpuInfo(
        id=sample.uuid,
        physical_index=sample.physical_index,
        name=sample.name,
        vram_total_mib=sample.vram_total_mib,
        vram_used_mib=sample.vram_used_mib,
        utilization_percent=sample.utilization_percent,
        temperature_celsius=sample.temperature_celsius,
        state=state,
        eligible=reason is None,
        unavailable_reason=reason,
        external_process_count=len(external_pids),
        last_heartbeat_at=datetime.now(UTC).isoformat(),
    )
