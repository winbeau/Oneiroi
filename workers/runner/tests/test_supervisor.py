from pathlib import Path

import pytest

from oneiroi_common.compute import PipelineSpec, ProfileTier
from oneiroi_common.generation import InternalI2VRequest
from oneiroi_runner.supervisor import ModelWorkerSupervisor


def fast_spec() -> PipelineSpec:
    return PipelineSpec(
        profileId="ltx23-distilled-fast-v1",
        tier=ProfileTier.FAST,
        ltxGitCommit="test-commit",
        checkpointPath="/models/distilled.safetensors",
        checkpointSha256="a" * 64,
        upsamplerPath="/models/upscaler.safetensors",
        upsamplerSha256="b" * 64,
        gemmaRoot="/models/gemma",
        gemmaRevision="test",
    )


@pytest.mark.asyncio
async def test_three_jobs_reuse_one_loaded_worker_and_release(tmp_path: Path) -> None:
    supervisor = ModelWorkerSupervisor(
        gpu_id="GPU-test-fast",
        physical_index=7,
        storage_root=tmp_path,
        adapter_name="fake",
        load_timeout_seconds=10,
        unload_timeout_seconds=2,
    )
    ready = await supervisor.load(fast_spec())
    worker_pid = ready.worker_pid

    results = []
    for index in range(3):
        results.append(
            await supervisor.run_job(
                InternalI2VRequest(jobId=f"job-{index}", prompt=f"prompt {index}")
            )
        )

    assert {result.worker_pid for result in results} == {worker_pid}
    assert supervisor.adapter_load_count == 1
    assert supervisor.jobs_completed == 3
    assert all(Path(result.output_path).is_file() for result in results)
    assert len({Path(result.output_path).parent.parent for result in results}) == 3

    report = await supervisor.release()

    assert report.succeeded
    assert supervisor.worker_pid is None


@pytest.mark.asyncio
async def test_load_is_idempotent_for_same_pipeline_spec(tmp_path: Path) -> None:
    supervisor = ModelWorkerSupervisor(
        gpu_id="GPU-test-fast",
        physical_index=0,
        storage_root=tmp_path,
        adapter_name="fake",
        load_timeout_seconds=10,
        unload_timeout_seconds=2,
    )

    first = await supervisor.load(fast_spec())
    second = await supervisor.load(fast_spec())

    assert first.worker_pid == second.worker_pid
    assert second.reused
    assert second.adapter_load_count == 1
    await supervisor.release()
