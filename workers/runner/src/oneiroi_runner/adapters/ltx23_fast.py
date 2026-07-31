from pathlib import Path
from typing import Any

from oneiroi_common.compute import PipelineSpec
from oneiroi_common.generation import InternalI2VRequest
from oneiroi_runner.adapters.base import CancelCheck, ProgressCallback


class Ltx23FastAdapter:
    """Hot LTX-2.3 Distilled adapter.

    All Torch/LTX imports intentionally remain inside methods so the Supervisor and
    Gateway never create a CUDA context. The child process sees one physical GPU as
    logical ``cuda:0`` through ``CUDA_VISIBLE_DEVICES=<GPU UUID>``.
    """

    def __init__(self) -> None:
        self.load_count = 0
        self.spec: PipelineSpec | None = None
        self.pipeline: Any = None

    def load(self, spec: PipelineSpec) -> None:
        if spec.tier.value != "fast":
            raise ValueError("the Fast adapter only accepts a Fast PipelineSpec")

        from ltx_pipelines.distilled import DistilledPipeline
        from ltx_pipelines.utils.quantization_factory import QuantizationKind
        from ltx_pipelines.utils.types import OffloadMode

        quantization = (
            QuantizationKind(spec.quantization).to_policy(spec.checkpoint_path)
            if spec.quantization != "none"
            else None
        )
        self.pipeline = DistilledPipeline(
            distilled_checkpoint_path=spec.checkpoint_path,
            spatial_upsampler_path=spec.upsampler_path,
            gemma_root=spec.gemma_root,
            loras=(),
            quantization=quantization,
            offload_mode=OffloadMode(spec.offload),
        )
        self.spec = spec
        self.load_count += 1

    def warm_up(self) -> None:
        if self.pipeline is None:
            raise RuntimeError("pipeline is not loaded")
        import torch

        torch.cuda.empty_cache()
        torch.cuda.synchronize()

    def generate(
        self,
        request: InternalI2VRequest,
        output_path: Path,
        progress: ProgressCallback,
        is_cancelled: CancelCheck,
    ) -> dict[str, object]:
        if self.pipeline is None:
            raise RuntimeError("pipeline is not loaded")
        if is_cancelled():
            raise InterruptedError("generation cancelled before preparation")

        from ltx_core.model.video_vae import TilingConfig, get_video_chunks_number
        from ltx_pipelines.utils.args import ImageConditioningInput
        from ltx_pipelines.utils.media_io import encode_video

        images = []
        if request.first_frame_path:
            images.append(
                ImageConditioningInput(
                    request.first_frame_path,
                    0,
                    request.first_frame_strength,
                    0,
                )
            )
        if request.last_frame_path:
            images.append(
                ImageConditioningInput(
                    request.last_frame_path,
                    request.num_frames - 1,
                    request.last_frame_strength,
                    0,
                )
            )

        import torch

        torch.cuda.empty_cache()
        torch.cuda.reset_peak_memory_stats()
        progress("preparing", 20, {})
        tiling_config = TilingConfig.default()
        video_chunks = get_video_chunks_number(request.num_frames, tiling_config)
        if is_cancelled():
            raise InterruptedError("generation cancelled before diffusion")
        progress("generating", 40, {"totalSteps": 11})
        with torch.inference_mode():
            video, audio = self.pipeline(
                prompt=request.prompt,
                seed=request.seed,
                height=request.height,
                width=request.width,
                num_frames=request.num_frames,
                frame_rate=request.frame_rate,
                images=images,
                tiling_config=tiling_config,
                enhance_prompt=request.enhance_prompt,
            )
            if is_cancelled():
                raise InterruptedError("generation cancelled before encoding")
            progress("encoding", 90, {})
            output_path.parent.mkdir(parents=True, exist_ok=True)
            encode_video(
                video=video,
                fps=int(request.frame_rate),
                audio=audio,
                output_path=str(output_path),
                video_chunks_number=video_chunks,
            )
        return {
            "profileId": self.spec.profile_id if self.spec else "unknown",
            "adapterLoadCount": self.load_count,
        }

    def close(self) -> None:
        self.pipeline = None
        self.spec = None
