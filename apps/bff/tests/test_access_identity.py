import json
import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

from oneiroi_bff.access_identity import (
    AccessAuthenticationError,
    CloudflareAccessJwtValidator,
)


def _token(private_key, **claims: object) -> str:
    return jwt.encode(
        claims,
        private_key,
        algorithm="RS256",
        headers={"kid": "key-1"},
    )


@pytest.mark.asyncio
async def test_cloudflare_access_validator_checks_signature_issuer_audience_and_expiry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private_key = rsa.generate_private_key(public_exponent=65_537, key_size=2_048)
    jwk = json.loads(RSAAlgorithm.to_jwk(private_key.public_key()))
    jwk.update({"kid": "key-1", "alg": "RS256", "use": "sig"})
    issuer = "https://team.cloudflareaccess.com"
    audience = "oneiroi-audience"
    validator = CloudflareAccessJwtValidator(
        issuer=issuer,
        audience=audience,
        jwks_url=f"{issuer}/cdn-cgi/access/certs",
    )

    async def fake_fetch():
        return {"keys": [jwk]}

    monkeypatch.setattr(validator, "_fetch_jwks", fake_fetch)
    now = int(time.time())
    valid = _token(
        private_key,
        iss=issuer,
        sub="authentik-user-a",
        aud=audience,
        iat=now,
        exp=now + 60,
    )
    identity = await validator.validate(valid)

    assert identity.issuer == issuer
    assert identity.subject == "authentik-user-a"
    assert identity.owner_id.startswith("access-")

    expired = _token(
        private_key,
        iss=issuer,
        sub="authentik-user-a",
        aud=audience,
        iat=now - 120,
        exp=now - 60,
    )
    with pytest.raises(AccessAuthenticationError):
        await validator.validate(expired)
