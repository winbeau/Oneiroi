import asyncio
import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from oneiroi_common.compute import ComputeSlot, GpuInfo, GpuState, PipelineSpec, ProfileTier
from oneiroi_common.runner_protocol import (
    JOB_EVENT_STREAM_TEMPLATE,
    RUNNER_CONTROL_STREAM_TEMPLATE,
    SLOT_CONTROL_STREAM_TEMPLATE,
    SLOT_JOB_STREAM_TEMPLATE,
    RunnerHeartbeat,
)
from oneiroi_common.studio import GenerationDraft
from oneiroi_gateway.redis.control_streams import RedisDirectedStreams
from oneiroi_gateway.services.job_execution import RedisJobExecutor
from oneiroi_gateway.services.pipeline_profiles import PipelineProfileCatalog
from oneiroi_gateway.services.runner_backend import RedisComputeBackend
from oneiroi_runner.redis_runtime import RedisRunnerRuntime
from oneiroi_runner.settings import RunnerSettings
from oneiroi_runner.supervisor import ModelWorkerSupervisor

pytestmark = pytest.mark.skipif(
    os.getenv("ONEIROI_TEST_REDIS") != "1",
    reason="set ONEIROI_TEST_REDIS=1 for the loopback Redis integration test",
)


def spec(tier: ProfileTier) -> PipelineSpec:
    return PipelineSpec(
        profileId=f"test-{tier.value}",
        tier=tier,
        ltxGitCommit="test",
        checkpointPath=f"/models/{tier.value}.safetensors",
        checkpointSha256="a" * 64,
        upsamplerPath="/models/up.safetensors",
        upsamplerSha256="b" * 64,
        gemmaRoot="/models/gemma",
        gemmaRevision="test",
    )


@pytest.mark.asyncio
async def test_redis_gateway_runner_load_job_and_release(tmp_path: Path) -> None:
    suffix = uuid4().hex
    gpu_id = f"GPU-runtime-{suffix}"
    slot_id = f"slot-runtime-{suffix}"
    session_id = f"compute-runtime-{suffix}"
    job_id = f"job-runtime-{suffix}"
    redis_url = os.getenv("ONEIROI_GATEWAY_REDIS_URL", "redis://127.0.0.1:6379/0")
    settings = RunnerSettings(
        redis_url=redis_url,
        name=f"runner-{suffix}",
        gpu_id=gpu_id,
        physical_index=7,
        storage_root=tmp_path / "jobs",
        adapter_name="fake",
        heartbeat_seconds=0.05,
    )
    supervisor = ModelWorkerSupervisor(
        gpu_id=gpu_id,
        physical_index=7,
        storage_root=settings.storage_root,
        adapter_name="fake",
        load_timeout_seconds=10,
        unload_timeout_seconds=2,
    )

    async def heartbeat() -> RunnerHeartbeat:
        return RunnerHeartbeat(
            runnerId=settings.name,
            slotId=slot_id,
            gpuId=gpu_id,
            physicalIndex=7,
            state=supervisor.state.value,
            vram_used_mib=0,
            vram_total_mib=81_559,
            workerPid=supervisor.worker_pid,
            occurredAt=datetime.now(UTC).isoformat(),
        )

    runtime = RedisRunnerRuntime(settings, supervisor, heartbeat_factory=heartbeat)
    streams = RedisDirectedStreams(redis_url)
    backend = RedisComputeBackend(
        streams,
        PipelineProfileCatalog(fast=spec(ProfileTier.FAST), hq=spec(ProfileTier.HQ)),
        command_timeout_seconds=10,
    )
    stop_event = asyncio.Event()
    runtime_task = asyncio.create_task(runtime.run(stop_event))
    try:
        await asyncio.sleep(0.05)
        loaded = await backend.load_slot(
            session_id,
            slot_id,
            GpuInfo(
                id=gpu_id,
                physicalIndex=7,
                name="H100 test",
                vramTotalMiB=81_559,
                eligible=True,
            ),
            ProfileTier.FAST,
            "fencing-test",
        )
        assert loaded["workerPid"] == supervisor.worker_pid

        draft = GenerationDraft(prompt="test prompt")
        fenced_job_id = f"job-fenced-{suffix}"
        await streams.publish_job(
            slot_id,
            fenced_job_id,
            {
                "fencingToken": "stale-token",
                "job": {
                    "id": fenced_job_id,
                    "draft": draft.model_dump(mode="json", by_alias=True),
                },
                "inputPaths": [None, None],
            },
        )
        with pytest.raises(RuntimeError, match="FENCING_TOKEN_MISMATCH"):
            await RedisJobExecutor(streams, timeout_seconds=10).execute(
                fenced_job_id,
                draft,
                settings.storage_root / fenced_job_id,
                (None, None),
                lambda _phase, _progress, _details: asyncio.sleep(0),
                lambda: False,
            )

        await streams.publish_job(
            slot_id,
            job_id,
            {
                "fencingToken": "fencing-test",
                "job": {
                    "id": job_id,
                    "draft": draft.model_dump(mode="json", by_alias=True),
                },
                "inputPaths": [None, None],
            },
        )
        result = await RedisJobExecutor(streams, timeout_seconds=10).execute(
            job_id,
            draft,
            settings.storage_root / job_id,
            (None, None),
            lambda _phase, _progress, _details: asyncio.sleep(0),
            lambda: False,
        )
        assert result.output_path.is_file()
        assert result.manifest_path.is_file()

        released = await backend.release_slot(
            session_id,
            ComputeSlot(
                id=slot_id,
                gpuId=gpu_id,
                physicalIndex=7,
                state=GpuState.READY,
                profile=ProfileTier.FAST,
            ),
            "fencing-test",
        )
        assert released
        assert supervisor.worker_pid is None
    finally:
        stop_event.set()
        await asyncio.wait_for(runtime_task, timeout=5)
        keys = [
            RUNNER_CONTROL_STREAM_TEMPLATE.format(gpu_id=gpu_id),
            SLOT_CONTROL_STREAM_TEMPLATE.format(slot_id=slot_id),
            SLOT_JOB_STREAM_TEMPLATE.format(slot_id=slot_id),
            JOB_EVENT_STREAM_TEMPLATE.format(job_id=job_id),
            JOB_EVENT_STREAM_TEMPLATE.format(job_id=f"job-fenced-{suffix}"),
        ]
        if keys:
            await streams.client.delete(*keys)
        await streams.close()
