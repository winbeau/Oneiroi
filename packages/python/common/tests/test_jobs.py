from oneiroi_common.jobs import JobStatus, QueueTier


def test_job_terminal_states_are_explicit() -> None:
    assert JobStatus.SUCCEEDED.is_terminal
    assert JobStatus.CANCELLED.is_terminal
    assert JobStatus.FAILED.is_terminal
    assert not JobStatus.GENERATING.is_terminal


def test_only_expected_queues_exist() -> None:
    assert {tier.value for tier in QueueTier} == {"fast", "hq"}
