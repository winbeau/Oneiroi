import asyncio
import multiprocessing as mp
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from multiprocessing.connection import Connection
from pathlib import Path

from oneiroi_common.compute import GpuState, PipelineSpec
from oneiroi_common.generation import GenerationResult, InternalI2VRequest
from oneiroi_runner.services.artifact_writer import ArtifactWriter
from oneiroi_runner.services.gpu_cleanup import (
    AlwaysReleasedMemoryVerifier,
    MemoryVerifier,
)
from oneiroi_runner.worker_process import worker_process_main


@dataclass(frozen=True, slots=True)
class WorkerReady:
    worker_pid: int
    load_seconds: float
    adapter_load_count: int
    reused: bool = False


@dataclass(frozen=True, slots=True)
class ReleaseReport:
    child_exited: bool
    memory_released: bool
    escalated_to_terminate: bool
    escalated_to_kill: bool

    @property
    def succeeded(self) -> bool:
        return self.child_exited and self.memory_released


class ModelWorkerSupervisor:
    def __init__(
        self,
        *,
        gpu_id: str,
        physical_index: int,
        storage_root: Path,
        adapter_name: str,
        baseline_vram_mib: int = 0,
        release_tolerance_mib: int = 512,
        memory_verifier: MemoryVerifier | None = None,
        load_timeout_seconds: float = 900,
        unload_timeout_seconds: float = 30,
    ) -> None:
        self.gpu_id = gpu_id
        self.physical_index = physical_index
        self.storage_root = storage_root
        self.adapter_name = adapter_name
        self.baseline_vram_mib = baseline_vram_mib
        self.release_tolerance_mib = release_tolerance_mib
        self.memory_verifier = memory_verifier or AlwaysReleasedMemoryVerifier()
        self.load_timeout_seconds = load_timeout_seconds
        self.unload_timeout_seconds = unload_timeout_seconds
        self.state = GpuState.EMPTY
        self.current_spec: PipelineSpec | None = None
        self.worker_pid: int | None = None
        self.adapter_load_count = 0
        self.jobs_completed = 0
        self._process: mp.Process | None = None
        self._connection: Connection | None = None
        self._job_lock = asyncio.Lock()
        self._writer = ArtifactWriter(storage_root)

    async def load(self, spec: PipelineSpec) -> WorkerReady:
        if self._process is not None and self._process.is_alive() and self.current_spec == spec:
            return WorkerReady(
                worker_pid=self.worker_pid or self._process.pid or 0,
                load_seconds=0,
                adapter_load_count=self.adapter_load_count,
                reused=True,
            )
        if self._process is not None:
            await self.release()

        self.state = GpuState.LOADING
        context = mp.get_context("spawn")
        parent, child = context.Pipe()
        process = context.Process(
            target=worker_process_main,
            kwargs={
                "connection": child,
                "gpu_id": self.gpu_id,
                "spec_payload": spec.model_dump(mode="json", by_alias=True),
                "adapter_name": self.adapter_name,
                "storage_root": str(self.storage_root),
            },
            name=f"oneiroi-model-worker-{self.physical_index}",
        )
        process.start()
        child.close()
        self._process = process
        self._connection = parent

        while True:
            message = await self._receive(self.load_timeout_seconds)
            message_type = message.get("type")
            if message_type == "ready":
                self.current_spec = spec
                self.worker_pid = int(message["workerPid"])
                self.adapter_load_count = int(message["adapterLoadCount"])
                self.state = GpuState.READY
                return WorkerReady(
                    worker_pid=self.worker_pid,
                    load_seconds=float(message["loadSeconds"]),
                    adapter_load_count=self.adapter_load_count,
                )
            if message_type == "load_failed":
                self.state = GpuState.ERROR
                await self._stop_failed_process()
                raise RuntimeError(f"model load failed: {message.get('message')}")

    async def run_job(
        self,
        request: InternalI2VRequest,
        on_event: Callable[[dict[str, object]], None] | None = None,
        *,
        timeout_seconds: float = 7_200,
    ) -> GenerationResult:
        if self.state is not GpuState.READY or self._connection is None:
            raise RuntimeError("model worker is not ready")
        async with self._job_lock:
            self.state = GpuState.BUSY
            self._connection.send(
                {"type": "run", "request": request.model_dump(mode="json", by_alias=True)}
            )
            try:
                while True:
                    message = await self._receive(timeout_seconds)
                    message_type = message.get("type")
                    if message_type == "progress":
                        if on_event:
                            on_event(message)
                        continue
                    if message_type == "succeeded":
                        result = GenerationResult.model_validate(message["result"])
                        result.validate_paths_within(self.storage_root)
                        self.jobs_completed += 1
                        return result
                    if message_type == "cancelled":
                        raise asyncio.CancelledError
                    if message_type == "failed":
                        raise RuntimeError(
                            f"generation failed: {message.get('error')}: {message.get('message')}"
                        )
            finally:
                if self._process is not None and self._process.is_alive():
                    self.state = GpuState.READY
                else:
                    self.state = GpuState.ERROR

    def cancel_job(self, job_id: str) -> None:
        _, _, cancel_path = self._writer.prepare_job(job_id)
        cancel_path.touch(exist_ok=True)

    async def release(self) -> ReleaseReport:
        self.state = GpuState.DRAINING
        async with self._job_lock:
            self.state = GpuState.UNLOADING
            process = self._process
            connection = self._connection
            terminated = False
            killed = False
            if process is not None and process.is_alive() and connection is not None:
                with suppress(BrokenPipeError, EOFError, OSError):
                    connection.send({"type": "shutdown"})
                await asyncio.to_thread(process.join, self.unload_timeout_seconds)
                if process.is_alive():
                    terminated = True
                    process.terminate()
                    await asyncio.to_thread(process.join, self.unload_timeout_seconds)
                if process.is_alive():
                    killed = True
                    process.kill()
                    await asyncio.to_thread(process.join, self.unload_timeout_seconds)

            child_exited = process is None or not process.is_alive()
            memory_released = await asyncio.to_thread(
                self.memory_verifier.released,
                self.gpu_id,
                self.baseline_vram_mib,
                self.release_tolerance_mib,
            )
            if connection is not None:
                connection.close()
            if process is not None:
                process.close()
            self._process = None
            self._connection = None
            self.worker_pid = None
            self.current_spec = None
            self.state = GpuState.EMPTY if child_exited and memory_released else GpuState.ERROR
            return ReleaseReport(child_exited, memory_released, terminated, killed)

    async def _receive(self, timeout_seconds: float) -> dict[str, object]:
        connection = self._connection
        if connection is None:
            raise RuntimeError("worker connection is closed")

        def receive() -> dict[str, object]:
            if not connection.poll(timeout_seconds):
                raise TimeoutError("model worker response timed out")
            return connection.recv()

        return await asyncio.to_thread(receive)

    async def _stop_failed_process(self) -> None:
        process = self._process
        if process is not None and process.is_alive():
            process.terminate()
            await asyncio.to_thread(process.join, self.unload_timeout_seconds)
        if self._connection is not None:
            self._connection.close()
        if process is not None:
            process.close()
        self._process = None
        self._connection = None
