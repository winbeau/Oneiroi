import pytest

from oneiroi_common.compute import (
    GpuInfo,
    GpuState,
    allocated_gpu_count,
    profile_plan_for_count,
)
from oneiroi_common.jobs import JobStatus


def test_dynamic_allocation_and_balanced_profile_matrix() -> None:
    assert allocated_gpu_count(4, 3) == 3
    assert allocated_gpu_count(4, 3, allow_partial=False) == 0
    assert [(plan.fast, plan.hq) for plan in map(profile_plan_for_count, range(5))] == [
        (0, 0),
        (1, 0),
        (1, 1),
        (2, 1),
        (2, 2),
    ]


def test_gpu_requires_stable_uuid() -> None:
    with pytest.raises(ValueError, match="stable NVML UUID"):
        GpuInfo(
            id="0",
            physicalIndex=0,
            name="H100",
            vramTotalMiB=80_000,
            state=GpuState.EMPTY,
        )


def test_job_model_and_compute_states_are_separate() -> None:
    assert JobStatus.LOADING_MODEL.value == "loading_model"
    assert JobStatus.CANCEL_REQUESTED.value == "cancel_requested"
    assert not JobStatus.CANCEL_REQUESTED.is_terminal
