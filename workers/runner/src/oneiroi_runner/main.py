import asyncio
import logging
import os
import signal

from oneiroi_runner.settings import RunnerSettings, get_settings

logger = logging.getLogger(__name__)


def bind_gpu(settings: RunnerSettings) -> None:
    expected = settings.gpu_id
    current = os.environ.get("CUDA_VISIBLE_DEVICES")
    if current is not None and current != expected:
        raise RuntimeError(
            f"CUDA_VISIBLE_DEVICES={current!r} conflicts with configured GPU UUID {expected!r}"
        )
    os.environ["CUDA_VISIBLE_DEVICES"] = expected


async def serve(settings: RunnerSettings) -> None:
    bind_gpu(settings)
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()

    for signal_name in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signal_name, stop_event.set)

    logger.info(
        "runner started: name=%s queue=%s gpu=%s",
        settings.name,
        settings.queue.value,
        settings.gpu_id,
    )
    await stop_event.wait()
    logger.info("runner stopped: name=%s", settings.name)


def run() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    asyncio.run(serve(get_settings()))


if __name__ == "__main__":
    run()
