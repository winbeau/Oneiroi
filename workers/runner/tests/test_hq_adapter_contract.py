import pytest

from oneiroi_common.compute import PipelineSpec, ProfileTier
from oneiroi_runner.adapters.ltx23_hq import Ltx23HqAdapter


def fast_spec() -> PipelineSpec:
    return PipelineSpec(
        profileId="ltx23-distilled-fast-v1",
        tier=ProfileTier.FAST,
        ltxGitCommit="commit",
        checkpointPath="/models/fast.safetensors",
        checkpointSha256="a" * 64,
        upsamplerPath="/models/up.safetensors",
        upsamplerSha256="b" * 64,
        gemmaRoot="/models/gemma",
        gemmaRevision="revision",
    )


def test_hq_adapter_never_accepts_or_downgrades_fast_spec() -> None:
    with pytest.raises(ValueError, match="only accepts an HQ"):
        Ltx23HqAdapter().load(fast_spec())
