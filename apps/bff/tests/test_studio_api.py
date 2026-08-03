import json
import time
from pathlib import Path

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from httpx import ASGITransport, AsyncClient
from jwt.algorithms import RSAAlgorithm

from oneiroi_bff.access_identity import CloudflareAccessJwtValidator
from oneiroi_bff.main import create_app as create_bff
from oneiroi_bff.settings import BffSettings
from oneiroi_gateway.main import create_app as create_gateway
from oneiroi_gateway.settings import GatewaySettings


def _rsa_material() -> tuple[rsa.RSAPrivateKey, bytes, dict[str, object]]:
    private_key = rsa.generate_private_key(public_exponent=65_537, key_size=2_048)
    public_key = private_key.public_key()
    public_pem = public_key.public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    jwk = json.loads(RSAAlgorithm.to_jwk(public_key))
    jwk.update({"kid": "access-test-key", "alg": "RS256", "use": "sig"})
    return private_key, public_pem, jwk


def _private_pem(private_key: rsa.RSAPrivateKey) -> bytes:
    return private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )


def _access_token(
    private_key: rsa.RSAPrivateKey,
    *,
    issuer: str,
    audience: str,
    subject: str,
) -> str:
    now = int(time.time())
    return jwt.encode(
        {
            "iss": issuer,
            "sub": subject,
            "aud": [audience],
            "iat": now,
            "exp": now + 300,
        },
        private_key,
        algorithm="RS256",
        headers={"kid": "access-test-key"},
    )


@pytest.mark.asyncio
async def test_bff_proxies_conversation_put_and_preserves_owner() -> None:
    gateway = create_gateway(GatewaySettings())
    bff = create_bff(BffSettings(gateway_base_url="http://gateway"), gateway_app=gateway)
    transport = ASGITransport(app=bff)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        created = await client.post(
            "/v1/conversations",
            headers={"X-Oneiroi-User": "owner-a"},
            json={"title": "Original"},
        )
        conversation_id = created.json()["id"]
        updated = await client.put(
            f"/v1/conversations/{conversation_id}",
            headers={"X-Oneiroi-User": "owner-a"},
            json={"title": "Updated"},
        )
        repeated = await client.put(
            f"/v1/conversations/{conversation_id}",
            headers={"X-Oneiroi-User": "owner-a"},
            json={"title": "Updated"},
        )
        hidden = await client.get(
            f"/v1/conversations/{conversation_id}",
            headers={"X-Oneiroi-User": "owner-b"},
        )

    assert created.status_code == 201
    assert updated.json()["id"] == repeated.json()["id"] == conversation_id
    assert updated.json()["title"] == "Updated"
    assert hidden.status_code == 404


@pytest.mark.asyncio
async def test_bff_proxies_conversation_delete() -> None:
    gateway = create_gateway(GatewaySettings())
    bff = create_bff(BffSettings(gateway_base_url="http://gateway"), gateway_app=gateway)
    transport = ASGITransport(app=bff)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        created = await client.post(
            "/v1/conversations",
            headers={"X-Oneiroi-User": "owner-a"},
            json={"title": "To delete"},
        )
        conversation_id = created.json()["id"]
        deleted = await client.delete(
            f"/v1/conversations/{conversation_id}",
            headers={"X-Oneiroi-User": "owner-a"},
        )
        gone = await client.get(
            f"/v1/conversations/{conversation_id}",
            headers={"X-Oneiroi-User": "owner-a"},
        )

    assert deleted.status_code == 204
    assert gone.status_code == 404


@pytest.mark.asyncio
async def test_bff_proxies_prompt_enhance() -> None:
    gateway = create_gateway(GatewaySettings())
    bff = create_bff(BffSettings(gateway_base_url="http://gateway"), gateway_app=gateway)
    transport = ASGITransport(app=bff)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/v1/agent/prompt-enhance",
            json={"prompt": "a cat walking", "negativePrompt": "flicker"},
        )

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "AGENT_UNAVAILABLE"


@pytest.mark.asyncio
async def test_bff_proxies_title_summarize() -> None:
    gateway = create_gateway(GatewaySettings())
    bff = create_bff(BffSettings(gateway_base_url="http://gateway"), gateway_app=gateway)
    transport = ASGITransport(app=bff)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/v1/agent/title-summarize",
            json={"prompt": "a cat walking in rain"},
        )

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "AGENT_UNAVAILABLE"


@pytest.mark.asyncio
async def test_production_bff_verifies_access_and_isolates_subjects(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    access_private, _, access_jwk = _rsa_material()
    service_private, service_public_pem, _ = _rsa_material()
    private_key_file = tmp_path / "service-private.pem"
    public_key_file = tmp_path / "service-public.pem"
    private_key_file.write_bytes(_private_pem(service_private))
    private_key_file.chmod(0o600)
    public_key_file.write_bytes(service_public_pem)

    async def fake_fetch_jwks(_validator: CloudflareAccessJwtValidator) -> dict[str, object]:
        return {"keys": [access_jwk]}

    monkeypatch.setattr(CloudflareAccessJwtValidator, "_fetch_jwks", fake_fetch_jwks)
    issuer = "https://team.cloudflareaccess.com"
    audience = "oneiroi-access-audience"
    gateway = create_gateway(
        GatewaySettings(environment="production", service_public_key_file=public_key_file)
    )
    h100_bff = create_bff(
        BffSettings(
            environment="production",
            gateway_base_url="http://gateway",
            require_inbound_service_auth=True,
            service_public_key_file=public_key_file,
        ),
        gateway_app=gateway,
    )
    bff = create_bff(
        BffSettings(
            environment="production",
            gateway_base_url="http://h100-bff",
            access_issuer=issuer,
            access_audience=audience,
            access_jwks_url=f"{issuer}/cdn-cgi/access/certs",
            allowed_origins="https://video.icthub.top",
            service_private_key_file=private_key_file,
        ),
        gateway_app=h100_bff,
    )
    token_a = _access_token(
        access_private,
        issuer=issuer,
        audience=audience,
        subject="access-user-a",
    )
    token_b = _access_token(
        access_private,
        issuer=issuer,
        audience=audience,
        subject="access-user-b",
    )
    transport = ASGITransport(app=bff)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client.cookies.set("oneiroi_user", "forged-owner")
        missing = await client.get(
            "/v1/conversations",
            headers={"X-Oneiroi-User": "forged-owner"},
        )
        csrf_rejected = await client.post(
            "/v1/conversations",
            headers={"Cf-Access-Jwt-Assertion": token_a},
            json={"title": "Blocked"},
        )
        created = await client.post(
            "/v1/conversations",
            headers={
                "Cf-Access-Jwt-Assertion": token_a,
                "Origin": "https://video.icthub.top",
            },
            json={"title": "Private A"},
        )
        conversation_id = created.json()["id"]
        visible = await client.get(
            f"/v1/conversations/{conversation_id}",
            headers={"Cf-Access-Jwt-Assertion": token_a},
        )
        hidden = await client.get(
            f"/v1/conversations/{conversation_id}",
            headers={"Cf-Access-Jwt-Assertion": token_b},
        )

    assert missing.status_code == 401
    assert csrf_rejected.status_code == 403
    assert created.status_code == 201
    assert visible.status_code == 200
    assert hidden.status_code == 404


@pytest.mark.asyncio
async def test_bff_rejects_oversized_body_before_contacting_gateway() -> None:
    bff = create_bff(
        BffSettings(
            gateway_base_url="http://127.0.0.1:9",
            max_upload_bytes=8,
        )
    )
    transport = ASGITransport(app=bff)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/v1/conversations", content=b"123456789")

    assert response.status_code == 413


@pytest.mark.asyncio
async def test_bff_maps_gateway_unavailable_without_simulating_success(monkeypatch) -> None:
    monkeypatch.setenv("ALL_PROXY", "socks5h://127.0.0.1:9")
    monkeypatch.setenv("NO_PROXY", "")
    bff = create_bff(
        BffSettings(
            gateway_base_url="http://127.0.0.1:9",
            request_timeout_seconds=0.1,
        )
    )
    transport = ASGITransport(app=bff)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/v1/conversations", json={"title": "No gateway"})

    assert response.status_code == 503
    assert response.json()["detail"] == "GATEWAY_UNAVAILABLE"
