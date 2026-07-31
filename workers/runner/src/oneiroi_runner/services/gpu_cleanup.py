from dataclasses import dataclass
from typing import Protocol


class MemoryVerifier(Protocol):
    def released(self, gpu_id: str, baseline_mib: int, tolerance_mib: int) -> bool: ...


@dataclass(slots=True)
class NvmlMemoryVerifier:
    def released(self, gpu_id: str, baseline_mib: int, tolerance_mib: int) -> bool:
        import pynvml

        pynvml.nvmlInit()
        try:
            handle = pynvml.nvmlDeviceGetHandleByUUID(gpu_id)
            memory = pynvml.nvmlDeviceGetMemoryInfo(handle)
            used_mib = memory.used // (1024 * 1024)
            return used_mib <= baseline_mib + tolerance_mib
        finally:
            pynvml.nvmlShutdown()


class AlwaysReleasedMemoryVerifier:
    def released(self, gpu_id: str, baseline_mib: int, tolerance_mib: int) -> bool:
        return True
