import os

import pytest

from oneiroi_common.jobs import QueueTier
from oneiroi_runner.main import bind_gpu
from oneiroi_runner.settings import RunnerSettings


def test_runner_defaults_to_first_fast_gpu() -> None:
    settings = RunnerSettings()

    assert settings.name == "fast-0"
    assert settings.queue is QueueTier.FAST
    assert settings.gpu_device == 0


def test_runner_binds_configured_gpu(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CUDA_VISIBLE_DEVICES", raising=False)

    bind_gpu(RunnerSettings(gpu_device=2, name="hq-0", queue=QueueTier.HQ))

    assert os.environ["CUDA_VISIBLE_DEVICES"] == "2"


def test_runner_rejects_conflicting_gpu_binding(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "1")

    with pytest.raises(RuntimeError, match="conflicts"):
        bind_gpu(RunnerSettings(gpu_device=0))
