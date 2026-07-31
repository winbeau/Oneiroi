from pathlib import Path
from typing import Any

from oneiroi_common.compute import PipelineSpec
from oneiroi_common.generation import InternalI2VRequest
from oneiroi_runner.adapters.base import CancelCheck, ProgressCallback


class Ltx23HqAdapter:
    """LTX-2.3 Dev/HQ adapter with a warmed immutable PipelineSpec."""

    def __init__(self) -> None:
        self.load_count = 0
        self.spec: PipelineSpec | None = None
        self.pipeline: Any = None
        self._registry: Any = None

    def load(self, spec: PipelineSpec) -> None:
        if spec.tier.value != "hq":
            raise ValueError("the HQ adapter only accepts an HQ PipelineSpec")
        if not spec.lora_paths_and_scales:
            raise ValueError("HQ PipelineSpec requires the distilled LoRA")

        from ltx_core.loader import LTXV_LORA_COMFY_RENAMING_MAP, LoraPathStrengthAndSDOps
        from ltx_core.loader.registry import StateDictRegistry
        from ltx_pipelines.ti2vid_two_stages_hq import TI2VidTwoStagesHQPipeline
        from ltx_pipelines.utils.allocator_trim_strategy import AllocatorTrimStrategy
        from ltx_pipelines.utils.quantization_factory import QuantizationKind
        from ltx_pipelines.utils.types import OffloadMode

        quantization = (
            QuantizationKind(spec.quantization).to_policy(spec.checkpoint_path)
            if spec.quantization != "none"
            else None
        )
        lora_path, lora_scale = spec.lora_paths_and_scales[0]
        distilled_lora = [
            LoraPathStrengthAndSDOps(
                path=lora_path,
                strength=lora_scale,
                sd_ops=LTXV_LORA_COMFY_RENAMING_MAP,
            )
        ]
        self._registry = StateDictRegistry()
        self.pipeline = TI2VidTwoStagesHQPipeline(
            checkpoint_path=spec.checkpoint_path,
            distilled_lora=distilled_lora,
            distilled_lora_strength_stage_1=0.25,
            distilled_lora_strength_stage_2=0.5,
            spatial_upsampler_path=spec.upsampler_path,
            gemma_root=spec.gemma_root,
            loras=(),
            quantization=quantization,
            registry=self._registry,
            offload_mode=OffloadMode(spec.offload),
            alloc_trim_strategy=AllocatorTrimStrategy.DEFER,
        )
        self.spec = spec
        self.load_count += 1

    def warm_up(self) -> None:
        if self.pipeline is None:
            raise RuntimeError("pipeline is not loaded")
        import torch

        with torch.inference_mode():
            video, _ = self._infer(
                prompt="A stable cinematic scene with subtle natural motion.",
                negative_prompt="flicker, distortion, unstable geometry",
                seed=0,
                height=512,
                width=768,
                num_frames=9,
                frame_rate=24,
                num_inference_steps=2,
                images=[],
                enhance_prompt=False,
            )
            for _ in video:
                pass
        torch.cuda.synchronize()

    def _infer(
        self,
        *,
        prompt: str,
        negative_prompt: str,
        seed: int,
        height: int,
        width: int,
        num_frames: int,
        frame_rate: float,
        num_inference_steps: int,
        images: list[Any],
        enhance_prompt: bool,
    ) -> tuple[Any, Any]:
        if self.pipeline is None:
            raise RuntimeError("HQ pipeline is not loaded")

        from ltx_core.components.guiders import MultiModalGuiderParams
        from ltx_core.model.video_vae import TilingConfig
        from ltx_pipelines.utils.constants import LTX_2_3_HQ_PARAMS

        params = LTX_2_3_HQ_PARAMS
        video_guider = params.video_guider_params
        audio_guider = params.audio_guider_params
        return self.pipeline(
            prompt=prompt,
            negative_prompt=negative_prompt,
            seed=seed,
            height=height,
            width=width,
            num_frames=num_frames,
            frame_rate=frame_rate,
            num_inference_steps=num_inference_steps,
            video_guider_params=MultiModalGuiderParams(
                cfg_scale=video_guider.cfg_scale,
                stg_scale=video_guider.stg_scale,
                rescale_scale=video_guider.rescale_scale,
                modality_scale=video_guider.modality_scale,
                skip_step=video_guider.skip_step,
                stg_blocks=video_guider.stg_blocks,
            ),
            audio_guider_params=MultiModalGuiderParams(
                cfg_scale=audio_guider.cfg_scale,
                stg_scale=audio_guider.stg_scale,
                rescale_scale=audio_guider.rescale_scale,
                modality_scale=audio_guider.modality_scale,
                skip_step=audio_guider.skip_step,
                stg_blocks=audio_guider.stg_blocks,
            ),
            images=images,
            tiling_config=TilingConfig.default(),
            enhance_prompt=enhance_prompt,
        )

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

        import torch
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

        torch.cuda.reset_peak_memory_stats()
        progress("preparing", 20, {})
        tiling_config = TilingConfig.default()
        video_chunks = get_video_chunks_number(request.num_frames, tiling_config)
        if is_cancelled():
            raise InterruptedError("generation cancelled before HQ diffusion")
        progress("generating", 40, {"totalSteps": request.num_inference_steps + 3})
        with torch.inference_mode():
            video, audio = self._infer(
                prompt=request.prompt,
                negative_prompt=request.negative_prompt,
                seed=request.seed,
                height=request.height,
                width=request.width,
                num_frames=request.num_frames,
                frame_rate=request.frame_rate,
                num_inference_steps=request.num_inference_steps,
                images=images,
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
            "hq": True,
        }

    def close(self) -> None:
        if self._registry is not None:
            self._registry.clear()
        self._registry = None
        self.pipeline = None
        self.spec = None
