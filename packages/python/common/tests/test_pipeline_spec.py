from oneiroi_common.compute import PipelineSpec, ProfileTier


def spec(**updates) -> PipelineSpec:
    values = {
        "profileId": "ltx23-distilled-fast-v1",
        "tier": ProfileTier.FAST,
        "ltxGitCommit": "commit",
        "checkpointPath": "/models/fast.safetensors",
        "checkpointSha256": "a" * 64,
        "upsamplerPath": "/models/up.safetensors",
        "upsamplerSha256": "b" * 64,
        "gemmaRoot": "/models/gemma",
        "gemmaRevision": "revision",
    }
    values.update(updates)
    return PipelineSpec(**values)


def test_pipeline_identity_covers_every_runtime_input() -> None:
    baseline = spec()

    assert baseline.identity == spec().identity
    assert baseline.identity != spec(attentionBackend="flash").identity
    assert baseline.identity != spec(checkpointSha256="c" * 64).identity
    assert baseline.identity != spec(runtimePolicyVersion="v2").identity
