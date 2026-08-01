from dataclasses import dataclass

from oneiroi_common.compute import (
    FAST_PROFILE_ID,
    HQ_PROFILE_ID,
    PipelineSpec,
    ProfileTier,
)
from oneiroi_gateway.settings import GatewaySettings


@dataclass(frozen=True, slots=True)
class PipelineProfileCatalog:
    fast: PipelineSpec
    hq: PipelineSpec

    @classmethod
    def from_settings(cls, settings: GatewaySettings) -> "PipelineProfileCatalog":
        required = {
            "ONEIROI_GATEWAY_LTX_GIT_COMMIT": settings.ltx_git_commit,
            "ONEIROI_GATEWAY_LTX_DISTILLED_CHECKPOINT_PATH": (
                settings.ltx_distilled_checkpoint_path
            ),
            "ONEIROI_GATEWAY_LTX_DISTILLED_CHECKPOINT_SHA256": (
                settings.ltx_distilled_checkpoint_sha256
            ),
            "ONEIROI_GATEWAY_LTX_DEV_CHECKPOINT_PATH": settings.ltx_dev_checkpoint_path,
            "ONEIROI_GATEWAY_LTX_DEV_CHECKPOINT_SHA256": (
                settings.ltx_dev_checkpoint_sha256
            ),
            "ONEIROI_GATEWAY_LTX_DISTILLED_LORA_PATH": settings.ltx_distilled_lora_path,
            "ONEIROI_GATEWAY_LTX_DISTILLED_LORA_SHA256": (
                settings.ltx_distilled_lora_sha256
            ),
            "ONEIROI_GATEWAY_LTX_UPSAMPLER_PATH": settings.ltx_upsampler_path,
            "ONEIROI_GATEWAY_LTX_UPSAMPLER_SHA256": settings.ltx_upsampler_sha256,
            "ONEIROI_GATEWAY_LTX_GEMMA_ROOT": settings.ltx_gemma_root,
            "ONEIROI_GATEWAY_LTX_GEMMA_REVISION": settings.ltx_gemma_revision,
        }
        missing = [name for name, value in required.items() if not value]
        if missing:
            raise RuntimeError(f"missing Runner profile settings: {', '.join(missing)}")
        common = {
            "ltxGitCommit": settings.ltx_git_commit,
            "upsamplerPath": settings.ltx_upsampler_path,
            "upsamplerSha256": settings.ltx_upsampler_sha256,
            "gemmaRoot": settings.ltx_gemma_root,
            "gemmaRevision": settings.ltx_gemma_revision,
            "quantization": "fp8-cast",
            "offload": "none",
            "dtype": "bfloat16",
            "attentionBackend": "sdpa",
            "compileMode": "disabled",
        }
        return cls(
            fast=PipelineSpec(
                profileId=FAST_PROFILE_ID,
                tier=ProfileTier.FAST,
                checkpointPath=settings.ltx_distilled_checkpoint_path,
                checkpointSha256=settings.ltx_distilled_checkpoint_sha256,
                runtimePolicyVersion="oneiroi-fast-v1",
                **common,
            ),
            hq=PipelineSpec(
                profileId=HQ_PROFILE_ID,
                tier=ProfileTier.HQ,
                checkpointPath=settings.ltx_dev_checkpoint_path,
                checkpointSha256=settings.ltx_dev_checkpoint_sha256,
                loraPathsAndScales=((settings.ltx_distilled_lora_path, 1.0),),
                loraSha256s=(settings.ltx_distilled_lora_sha256,),
                runtimePolicyVersion="oneiroi-hq-v1",
                **common,
            ),
        )

    def get(self, tier: ProfileTier) -> PipelineSpec:
        return self.hq if tier is ProfileTier.HQ else self.fast
