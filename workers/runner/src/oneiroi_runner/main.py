import asyncio
import logging
import os
import signal

from oneiroi_runner.redis_runtime import RedisRunnerRuntime
from oneiroi_runner.services.gpu_cleanup import NvmlMemoryVerifier
from oneiroi_runner.settings import RunnerSettings, get_settings
from oneiroi_runner.supervisor import ModelWorkerSupervisor

logger = logging.getLogger(__name__)


def bind_gpu(settings: RunnerSettings) -> None:
    expected = settings.gpu_id
    current = os.environ.get("CUDA_VISIBLE_DEVICES")
    if current is not None and current != expected:
        raise RuntimeError(
            f"CUDA_VISIBLE_DEVICES={current!r} conflicts with configured GPU UUID {expected!r}"
        )
    os.environ["CUDA_VISIBLE_DEVICES"] = expected


def validate_process_identity(settings: RunnerSettings) -> None:
    if settings.environment != "production":
        return
    effective_uid = getattr(os, "geteuid", None)
    if effective_uid is None:
        raise RuntimeError("production Runner requires a verifiable dedicated non-root user")
    if effective_uid() == 0:
        raise RuntimeError("production Runner must use a dedicated non-root user")


async def serve(settings: RunnerSettings) -> None:
    validate_process_identity(settings)
    bind_gpu(settings)
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()

    for signal_name in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signal_name, stop_event.set)

    supervisor = ModelWorkerSupervisor(
        gpu_id=settings.gpu_id,
        physical_index=settings.physical_index,
        storage_root=settings.storage_root,
        adapter_name=settings.adapter_name,
        baseline_vram_mib=settings.baseline_vram_mib,
        release_tolerance_mib=settings.release_tolerance_mib,
        memory_verifier=NvmlMemoryVerifier(),
        load_timeout_seconds=settings.load_timeout_seconds,
        unload_timeout_seconds=settings.unload_timeout_seconds,
    )
    runtime = RedisRunnerRuntime(settings, supervisor)
    logger.info(
        "runner started: name=%s queue=%s gpu=%s",
        settings.name,
        settings.queue.value,
        settings.gpu_id,
    )
    await runtime.run(stop_event)
    logger.info("runner stopped: name=%s", settings.name)


def run() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    asyncio.run(serve(get_settings()))


if __name__ == "__main__":
    run()
