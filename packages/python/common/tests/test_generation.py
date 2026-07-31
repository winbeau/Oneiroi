import pytest

from oneiroi_common.generation import InternalI2VRequest


def test_ltx_dimensions_and_frames_are_validated() -> None:
    request = InternalI2VRequest(jobId="job-a", prompt="test", width=768, height=512, numFrames=9)
    assert request.num_frames == 9

    with pytest.raises(ValueError, match="divisible by 64"):
        InternalI2VRequest(jobId="job-a", prompt="test", width=770)
    with pytest.raises(ValueError, match=r"8K\+1"):
        InternalI2VRequest(jobId="job-a", prompt="test", numFrames=10)
