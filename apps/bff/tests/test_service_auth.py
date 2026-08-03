from pathlib import Path

import pytest

from oneiroi_bff.service_auth import (
    ServiceAssertionSigner,
    ServiceAuthConfigurationError,
)


@pytest.fixture
def rsa_key(tmp_path: Path) -> Path:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    path = tmp_path / "service-private.pem"
    path.write_bytes(pem)
    path.chmod(0o600)
    return path


def _signer(key: Path, *, lifetime: int = 300, clock=None) -> ServiceAssertionSigner:
    return ServiceAssertionSigner(
        key,
        issuer="oneiroi-pi-bff",
        audience="oneiroi-h100-gateway",
        key_id="oneiroi-pi-1",
        lifetime_seconds=lifetime,
        clock=clock,
    )


def test_signer_reuses_assertion_per_owner(rsa_key: Path) -> None:
    clock = {"now": 1_000.0}
    signer = _signer(rsa_key, clock=lambda: clock["now"])
    first = signer.issue("owner-a")
    second = signer.issue("owner-a")
    assert first == second

    other = signer.issue("owner-b")
    assert other != first
    assert signer.issue("owner-b") == other


def test_signer_mints_fresh_assertion_after_ttl(rsa_key: Path) -> None:
    clock = {"now": 1_000.0}
    signer = _signer(rsa_key, lifetime=60, clock=lambda: clock["now"])
    first = signer.issue("owner-a")
    clock["now"] += 55  # beyond lifetime minus the reuse margin (12s)
    refreshed = signer.issue("owner-a")
    assert refreshed != first
    assert signer.issue("owner-a") == refreshed


def test_signer_requires_configuration() -> None:
    signer = _signer(None)
    with pytest.raises(ServiceAuthConfigurationError):
        signer.issue("owner-a")
