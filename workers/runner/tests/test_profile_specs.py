from oneiroi_common.compute import ProfileTier
from oneiroi_runner.adapters.profile_specs import (
    LtxProfilePaths,
    fast_pipeline_spec,
    hq_pipeline_spec,
)


def paths() -> LtxProfilePaths:
    return LtxProfilePaths(
        ltx_git_commit="commit",
        distilled_checkpoint_path="/models/fast.safetensors",
        distilled_checkpoint_sha256="a" * 64,
        dev_checkpoint_path="/models/dev.safetensors",
        dev_checkpoint_sha256="b" * 64,
        distilled_lora_path="/models/lora.safetensors",
        distilled_lora_sha256="c" * 64,
        upsampler_path="/models/up.safetensors",
        upsampler_sha256="d" * 64,
        gemma_root="/models/gemma",
        gemma_revision="revision",
    )


def test_fast_and_hq_specs_are_complete_and_distinct() -> None:
    fast = fast_pipeline_spec(paths())
    hq = hq_pipeline_spec(paths())

    assert fast.tier is ProfileTier.FAST
    assert hq.tier is ProfileTier.HQ
    assert hq.lora_paths_and_scales == (("/models/lora.safetensors", 1.0),)
    assert hq.lora_sha256s == ("c" * 64,)
    assert fast.identity != hq.identity
