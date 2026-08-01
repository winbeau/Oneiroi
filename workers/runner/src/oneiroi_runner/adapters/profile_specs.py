from dataclasses import dataclass

from oneiroi_common.compute import (
    FAST_PROFILE_ID,
    HQ_PROFILE_ID,
    PipelineSpec,
    ProfileTier,
)


@dataclass(frozen=True, slots=True)
class LtxProfilePaths:
    ltx_git_commit: str
    distilled_checkpoint_path: str
    distilled_checkpoint_sha256: str
    dev_checkpoint_path: str
    dev_checkpoint_sha256: str
    distilled_lora_path: str
    distilled_lora_sha256: str
    upsampler_path: str
    upsampler_sha256: str
    gemma_root: str
    gemma_revision: str


def fast_pipeline_spec(paths: LtxProfilePaths) -> PipelineSpec:
    return PipelineSpec(
        profileId=FAST_PROFILE_ID,
        tier=ProfileTier.FAST,
        ltxGitCommit=paths.ltx_git_commit,
        checkpointPath=paths.distilled_checkpoint_path,
        checkpointSha256=paths.distilled_checkpoint_sha256,
        upsamplerPath=paths.upsampler_path,
        upsamplerSha256=paths.upsampler_sha256,
        gemmaRoot=paths.gemma_root,
        gemmaRevision=paths.gemma_revision,
        quantization="fp8-cast",
        offload="none",
        dtype="bfloat16",
        attentionBackend="sdpa",
        compileMode="disabled",
        runtimePolicyVersion="oneiroi-fast-v1",
    )


def hq_pipeline_spec(paths: LtxProfilePaths) -> PipelineSpec:
    return PipelineSpec(
        profileId=HQ_PROFILE_ID,
        tier=ProfileTier.HQ,
        ltxGitCommit=paths.ltx_git_commit,
        checkpointPath=paths.dev_checkpoint_path,
        checkpointSha256=paths.dev_checkpoint_sha256,
        upsamplerPath=paths.upsampler_path,
        upsamplerSha256=paths.upsampler_sha256,
        gemmaRoot=paths.gemma_root,
        gemmaRevision=paths.gemma_revision,
        loraPathsAndScales=((paths.distilled_lora_path, 1.0),),
        loraSha256s=(paths.distilled_lora_sha256,),
        quantization="fp8-cast",
        offload="none",
        dtype="bfloat16",
        attentionBackend="sdpa",
        compileMode="disabled",
        runtimePolicyVersion="oneiroi-hq-v1",
    )
