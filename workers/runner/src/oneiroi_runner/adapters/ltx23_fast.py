from pathlib import Path
from typing import Any

from oneiroi_common.compute import PipelineSpec
from oneiroi_common.generation import InternalI2VRequest
from oneiroi_runner.adapters.base import CancelCheck, ProgressCallback


class Ltx23FastAdapter:
    """Hot LTX-2.3 Distilled adapter with one persistent transformer.

    All Torch/LTX imports intentionally remain inside methods so the Supervisor and
    Gateway never create a CUDA context. The child process sees one physical GPU as
    logical ``cuda:0`` through ``CUDA_VISIBLE_DEVICES=<GPU UUID>``.
    """

    def __init__(self) -> None:
        self.load_count = 0
        self.spec: PipelineSpec | None = None
        self.pipeline: Any = None
        self.transformer: Any = None
        self._transformer_context: Any = None
        self._registry: Any = None

    def load(self, spec: PipelineSpec) -> None:
        if spec.tier.value != "fast":
            raise ValueError("the Fast adapter only accepts a Fast PipelineSpec")

        from ltx_core.loader.registry import StateDictRegistry
        from ltx_pipelines.distilled import DistilledPipeline
        from ltx_pipelines.utils.quantization_factory import QuantizationKind
        from ltx_pipelines.utils.types import OffloadMode

        quantization = (
            QuantizationKind(spec.quantization).to_policy(spec.checkpoint_path)
            if spec.quantization != "none"
            else None
        )
        self._registry = StateDictRegistry()
        self.pipeline = DistilledPipeline(
            distilled_checkpoint_path=spec.checkpoint_path,
            spatial_upsampler_path=spec.upsampler_path,
            gemma_root=spec.gemma_root,
            loras=(),
            quantization=quantization,
            registry=self._registry,
            offload_mode=OffloadMode(spec.offload),
        )
        self.spec = spec
        self.load_count += 1

    def warm_up(self) -> None:
        if self.pipeline is None:
            raise RuntimeError("pipeline is not loaded")
        import torch

        self._transformer_context = self.pipeline.stage.model_context()
        self.transformer = self._transformer_context.__enter__()
        with torch.inference_mode():
            video, _ = self._infer(
                prompt="A stable cinematic scene with subtle natural motion.",
                seed=0,
                height=512,
                width=768,
                num_frames=9,
                frame_rate=24,
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
        seed: int,
        height: int,
        width: int,
        num_frames: int,
        frame_rate: float,
        images: list[Any],
        enhance_prompt: bool,
    ) -> tuple[Any, Any]:
        if self.pipeline is None or self.transformer is None:
            raise RuntimeError("hot transformer is not ready")

        import torch
        from ltx_core.components.noisers import GaussianNoiser
        from ltx_pipelines.utils.blocks import upsample_video, vae_decode_audio
        from ltx_pipelines.utils.constants import DISTILLED_SIGMAS, STAGE_2_DISTILLED_SIGMAS
        from ltx_pipelines.utils.denoisers import SimpleDenoiser
        from ltx_pipelines.utils.helpers import combined_image_conditionings
        from ltx_pipelines.utils.types import ModalitySpec

        generator = torch.Generator(device=self.pipeline.device).manual_seed(seed)
        noiser = GaussianNoiser(generator=generator)
        dtype = torch.bfloat16
        (context,) = self.pipeline.prompt_encoder(
            [prompt],
            enhance_first_prompt=enhance_prompt,
            enhance_prompt_image=images[0][0] if images else None,
        )
        video_context, audio_context = context.video_encoding, context.audio_encoding

        stage_1_sigmas = DISTILLED_SIGMAS.to(dtype=torch.float32, device=self.pipeline.device)
        stage_1_width, stage_1_height = width // 2, height // 2
        stage_1_conditionings = self.pipeline.image_conditioner(
            lambda encoder: combined_image_conditionings(
                images=images,
                height=stage_1_height,
                width=stage_1_width,
                video_encoder=encoder,
                dtype=dtype,
                device=self.pipeline.device,
            )
        )
        video_state, audio_state = self.pipeline.stage.run(
            self.transformer,
            denoiser=SimpleDenoiser(video_context, audio_context),
            sigmas=stage_1_sigmas,
            noiser=noiser,
            width=stage_1_width,
            height=stage_1_height,
            frames=num_frames,
            fps=frame_rate,
            video=ModalitySpec(context=video_context, conditionings=stage_1_conditionings),
            audio=ModalitySpec(context=audio_context),
        )

        encoder = self.pipeline.upsampler._encoder_builder.build(  # noqa: SLF001
            device=self.pipeline.device,
            dtype=self.pipeline.dtype,
        ).eval()
        upsampler = self.pipeline.upsampler._upsampler_builder.build(  # noqa: SLF001
            device=self.pipeline.device,
            dtype=self.pipeline.dtype,
        ).eval()
        try:
            upscaled_video_latent = upsample_video(
                latent=video_state.latent[:1],
                video_encoder=encoder,
                upsampler=upsampler,
            )
        finally:
            encoder.to("meta")
            upsampler.to("meta")
            torch.cuda.empty_cache()

        stage_2_sigmas = STAGE_2_DISTILLED_SIGMAS.to(
            dtype=torch.float32,
            device=self.pipeline.device,
        )
        stage_2_conditionings = self.pipeline.image_conditioner(
            lambda encoder: combined_image_conditionings(
                images=images,
                height=height,
                width=width,
                video_encoder=encoder,
                dtype=dtype,
                device=self.pipeline.device,
            )
        )
        video_state, audio_state = self.pipeline.stage.run(
            self.transformer,
            denoiser=SimpleDenoiser(video_context, audio_context),
            sigmas=stage_2_sigmas,
            noiser=noiser,
            width=width,
            height=height,
            frames=num_frames,
            fps=frame_rate,
            video=ModalitySpec(
                context=video_context,
                conditionings=stage_2_conditionings,
                noise_scale=stage_2_sigmas[0].item(),
                initial_latent=upscaled_video_latent,
            ),
            audio=ModalitySpec(
                context=audio_context,
                noise_scale=stage_2_sigmas[0].item(),
                initial_latent=audio_state.latent,
            ),
        )

        decoder = self.pipeline.video_decoder._decoder_builder.build(  # noqa: SLF001
            device=self.pipeline.device,
            dtype=self.pipeline.dtype,
        ).eval()
        decoded_video = decoder.decode_video(video_state.latent, None, generator)
        audio_decoder = self.pipeline.audio_decoder._decoder_builder.build(  # noqa: SLF001
            device=self.pipeline.device,
            dtype=self.pipeline.dtype,
        ).eval()
        vocoder = self.pipeline.audio_decoder._vocoder_builder.build(  # noqa: SLF001
            device=self.pipeline.device,
            dtype=self.pipeline.dtype,
        ).eval()
        decoded_audio = vae_decode_audio(audio_state.latent, audio_decoder, vocoder)

        def video_chunks():
            try:
                yield from decoded_video
            finally:
                decoder.to("meta")
                audio_decoder.to("meta")
                vocoder.to("meta")
                torch.cuda.empty_cache()

        return video_chunks(), decoded_audio

    def generate(
        self,
        request: InternalI2VRequest,
        output_path: Path,
        progress: ProgressCallback,
        is_cancelled: CancelCheck,
    ) -> dict[str, object]:
        if self.pipeline is None or self.transformer is None:
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
            raise InterruptedError("generation cancelled before diffusion")
        progress("generating", 40, {"totalSteps": 11})
        with torch.inference_mode():
            video, audio = self._infer(
                prompt=request.prompt,
                seed=request.seed,
                height=request.height,
                width=request.width,
                num_frames=request.num_frames,
                frame_rate=request.frame_rate,
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
            "hotTransformer": True,
        }

    def close(self) -> None:
        if self._transformer_context is not None:
            self._transformer_context.__exit__(None, None, None)
        if self._registry is not None:
            self._registry.clear()
        self.transformer = None
        self._transformer_context = None
        self._registry = None
        self.pipeline = None
        self.spec = None
