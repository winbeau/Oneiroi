import pytest
from httpx import ASGITransport, AsyncClient

from oneiroi_gateway.main import create_app
from oneiroi_gateway.settings import GatewaySettings


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
async def test_production_gateway_requires_private_identity_for_v1_routes() -> None:
    production = create_app(GatewaySettings(environment="production"))
    transport = ASGITransport(app=production)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        missing = await client.get("/v1/compute/capabilities")
        authenticated = await client.get(
            "/v1/compute/capabilities",
            headers={"X-Oneiroi-User": "owner-a"},
        )

    assert missing.status_code == 401
    assert authenticated.status_code == 200
