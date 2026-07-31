import os

import pytest

from oneiroi_common.jobs import QueueTier
from oneiroi_runner.main import bind_gpu
from oneiroi_runner.settings import RunnerSettings


def test_runner_defaults_are_unconfigured_not_fixed_to_gpu_zero() -> None:
    settings = RunnerSettings()

    assert settings.name == "runner-unconfigured"
    assert settings.queue is QueueTier.FAST
    assert settings.gpu_id == "GPU-unconfigured"


def test_runner_binds_configured_gpu_uuid(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CUDA_VISIBLE_DEVICES", raising=False)

    bind_gpu(RunnerSettings(gpu_id="GPU-2222", physical_index=2, name="runner-2"))

    assert os.environ["CUDA_VISIBLE_DEVICES"] == "GPU-2222"


def test_runner_rejects_conflicting_gpu_binding(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "GPU-1111")

    with pytest.raises(RuntimeError, match="conflicts"):
        bind_gpu(RunnerSettings(gpu_id="GPU-0000"))
