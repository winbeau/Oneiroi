from pathlib import Path

import pytest

from oneiroi_common.compute import PipelineSpec, ProfileTier
from oneiroi_common.generation import InternalI2VRequest
from oneiroi_runner.supervisor import ModelWorkerSupervisor


def fast_spec(profile_id: str = "ltx23-distilled-fast-v1") -> PipelineSpec:
    return PipelineSpec(
        profileId=profile_id,
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


@pytest.mark.asyncio
async def test_oom_fails_only_the_job_and_worker_remains_reusable(tmp_path: Path) -> None:
    supervisor = ModelWorkerSupervisor(
        gpu_id="GPU-test-fast",
        physical_index=0,
        storage_root=tmp_path,
        adapter_name="fake",
        load_timeout_seconds=10,
        unload_timeout_seconds=2,
    )
    await supervisor.load(fast_spec())

    with pytest.raises(RuntimeError, match="CUDA_OUT_OF_MEMORY"):
        await supervisor.run_job(InternalI2VRequest(jobId="job-oom", prompt="[oom]"))

    recovered = await supervisor.run_job(
        InternalI2VRequest(jobId="job-after-oom", prompt="normal")
    )
    assert Path(recovered.output_path).is_file()
    assert supervisor.jobs_completed == 1
    await supervisor.release()


@pytest.mark.asyncio
async def test_worker_crash_is_detected_and_release_leaves_no_child(tmp_path: Path) -> None:
    supervisor = ModelWorkerSupervisor(
        gpu_id="GPU-test-fast",
        physical_index=0,
        storage_root=tmp_path,
        adapter_name="fake",
        load_timeout_seconds=10,
        unload_timeout_seconds=1,
    )
    await supervisor.load(fast_spec())

    with pytest.raises(EOFError):
        await supervisor.run_job(InternalI2VRequest(jobId="job-crash", prompt="[crash]"))

    report = await supervisor.release()
    assert report.child_exited
    assert supervisor.worker_pid is None


@pytest.mark.asyncio
async def test_unload_timeout_escalates_to_terminate(tmp_path: Path) -> None:
    supervisor = ModelWorkerSupervisor(
        gpu_id="GPU-test-fast",
        physical_index=0,
        storage_root=tmp_path,
        adapter_name="fake",
        load_timeout_seconds=10,
        unload_timeout_seconds=0.05,
    )
    await supervisor.load(fast_spec("fake-unload-hang"))

    report = await supervisor.release()

    assert report.succeeded
    assert report.escalated_to_terminate
    assert not report.escalated_to_kill
