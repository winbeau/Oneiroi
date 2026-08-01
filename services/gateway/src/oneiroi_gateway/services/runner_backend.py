from uuid import uuid4

from oneiroi_common.compute import ComputeSlot, GpuInfo, ProfileTier
from oneiroi_common.runner_protocol import RunnerCommand, RunnerCommandType
from oneiroi_gateway.redis.control_streams import RedisDirectedStreams
from oneiroi_gateway.services.pipeline_profiles import PipelineProfileCatalog


class RedisComputeBackend:
    def __init__(
        self,
        streams: RedisDirectedStreams,
        profiles: PipelineProfileCatalog,
        *,
        command_timeout_seconds: float,
    ) -> None:
        self.streams = streams
        self.profiles = profiles
        self.command_timeout_seconds = command_timeout_seconds

    async def load_slot(
        self,
        session_id: str,
        slot_id: str,
        gpu: GpuInfo,
        profile: ProfileTier,
        fencing_token: str,
    ) -> dict[str, object]:
        spec = self.profiles.get(profile)
        command = RunnerCommand(
            commandId=f"command-{uuid4().hex}",
            commandType=RunnerCommandType.LOAD_PROFILE,
            slotId=slot_id,
            pipelineSpec=spec,
            payload={
                "sessionId": session_id,
                "gpuId": gpu.id,
                "fencingToken": fencing_token,
            },
        )
        await self.streams.publish_runner_command(gpu.id, command)
        result = await self.streams.wait_command_result(
            command.command_id,
            timeout_seconds=self.command_timeout_seconds,
        )
        if result.status == "failed":
            raise RuntimeError(result.error or "RUNNER_LOAD_FAILED")
        return {**result.payload, "pipelineSpecHash": spec.identity}

    async def release_slot(
        self,
        session_id: str,
        slot: ComputeSlot,
        fencing_token: str,
    ) -> bool:
        command = RunnerCommand(
            commandId=f"command-{uuid4().hex}",
            commandType=RunnerCommandType.UNLOAD,
            slotId=slot.id,
            payload={
                "sessionId": session_id,
                "gpuId": slot.gpu_id,
                "fencingToken": fencing_token,
            },
        )
        await self.streams.publish_slot_command(command)
        result = await self.streams.wait_command_result(
            command.command_id,
            timeout_seconds=self.command_timeout_seconds,
        )
        return result.status == "succeeded" and bool(result.payload.get("memoryReleased"))
