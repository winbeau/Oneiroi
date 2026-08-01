import hashlib
from pathlib import Path

import pytest

from oneiroi_runner.worker_process import _verify_file


def test_model_asset_hash_must_match(tmp_path: Path) -> None:
    asset = tmp_path / "model.safetensors"
    asset.write_bytes(b"trusted model bytes")
    expected = hashlib.sha256(asset.read_bytes()).hexdigest()

    _verify_file(str(asset), expected)

    with pytest.raises(RuntimeError, match="MODEL_HASH_MISMATCH"):
        _verify_file(str(asset), "0" * 64)
