from pathlib import Path

import pytest

from oneiroi_runner.services.artifact_writer import ArtifactWriter


def test_artifact_writer_keeps_jobs_in_isolated_directories(tmp_path: Path) -> None:
    writer = ArtifactWriter(tmp_path)
    first, manifest, cancel = writer.prepare_job("job-a")
    second, _, _ = writer.prepare_job("job-b")

    assert first == tmp_path / "job-a" / "output" / "result.mp4"
    assert manifest == tmp_path / "job-a" / "manifest.json"
    assert cancel.parent.is_dir()
    assert first.parent.parent != second.parent.parent


def test_artifact_writer_rejects_path_traversal(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="invalid job id"):
        ArtifactWriter(tmp_path).prepare_job("../escape")
