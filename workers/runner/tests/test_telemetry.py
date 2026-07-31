from oneiroi_common.compute import GpuState
from oneiroi_runner.telemetry import GpuTelemetrySample, InventoryPolicy, classify_gpu


def sample(index: int, *, used: int = 0, processes: tuple[int, ...] = ()) -> GpuTelemetrySample:
    return GpuTelemetrySample(
        uuid=f"GPU-{index:04d}",
        physical_index=index,
        name="NVIDIA H100 80GB HBM3",
        vram_total_mib=81_559,
        vram_used_mib=used,
        utilization_percent=0,
        temperature_celsius=30,
        compute_process_pids=processes,
    )


def test_non_contiguous_idle_gpus_are_eligible() -> None:
    policy = InventoryPolicy()
    result = [classify_gpu(sample(index), policy) for index in (0, 1, 2, 7)]

    assert [gpu.physical_index for gpu in result if gpu.eligible] == [0, 1, 2, 7]


def test_external_process_and_vram_threshold_are_not_idle() -> None:
    policy = InventoryPolicy()
    foreign = classify_gpu(sample(3, processes=(9123,)), policy)
    memory_busy = classify_gpu(sample(4, used=2_048), policy)

    assert foreign.state is GpuState.FOREIGN_BUSY
    assert foreign.unavailable_reason == "EXTERNAL_COMPUTE_PROCESS"
    assert memory_busy.unavailable_reason == "VRAM_ABOVE_IDLE_THRESHOLD"


def test_oneiroi_worker_pid_is_not_misclassified_as_foreign() -> None:
    gpu = classify_gpu(
        sample(5, processes=(123,)),
        InventoryPolicy(),
        oneiroi_worker_pids=frozenset({123}),
    )

    assert gpu.eligible
    assert gpu.external_process_count == 0
