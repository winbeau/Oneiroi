import time
from pathlib import Path

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from httpx import ASGITransport, AsyncClient

from oneiroi_gateway.main import create_app
from oneiroi_gateway.settings import GatewaySettings


def _service_material(tmp_path: Path) -> tuple[Path, str]:
    private_key = rsa.generate_private_key(public_exponent=65_537, key_size=2_048)
    public_key_file = tmp_path / "service-public.pem"
    public_key_file.write_bytes(
        private_key.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )
    now = int(time.time())
    assertion = jwt.encode(
        {
            "iss": "oneiroi-pi-bff",
            "sub": "owner-a",
            "aud": "oneiroi-h100-gateway",
            "iat": now,
            "exp": now + 60,
            "jti": "gateway-health-test",
        },
        private_key,
        algorithm="RS256",
    )
    return public_key_file, assertion


@pytest.mark.asyncio
async def test_health_endpoint() -> None:
    transport = ASGITransport(app=create_app(GatewaySettings()))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/healthz")

    assert response.status_code == 200
    assert response.json()["service"] == "gateway"


@pytest.mark.asyncio
async def test_queue_catalog_is_bounded() -> None:
    transport = ASGITransport(app=create_app(GatewaySettings()))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/v1/system/queues")

    assert response.status_code == 200
    assert response.json() == {"queues": ["fast", "hq"]}


@pytest.mark.asyncio
async def test_production_gateway_requires_signed_service_identity(tmp_path: Path) -> None:
    public_key_file, assertion = _service_material(tmp_path)
    production = create_app(
        GatewaySettings(environment="production", service_public_key_file=public_key_file)
    )
    transport = ASGITransport(app=production)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        missing = await client.get("/v1/compute/capabilities")
        forged = await client.get(
            "/v1/compute/capabilities",
            headers={"X-Oneiroi-User": "owner-a", "X-Oneiroi-Service-Assertion": "forged"},
        )
        authenticated = await client.get(
            "/v1/compute/capabilities",
            headers={
                "X-Oneiroi-User": "owner-a",
                "X-Oneiroi-Service-Assertion": assertion,
            },
        )

    assert missing.status_code == 401
    assert forged.status_code == 401
    assert authenticated.status_code == 200
