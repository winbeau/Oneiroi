import pytest
from httpx import ASGITransport, AsyncClient

from oneiroi_bff.main import create_app
from oneiroi_bff.settings import BffSettings


@pytest.mark.asyncio
async def test_health_endpoint() -> None:
    transport = ASGITransport(app=create_app(BffSettings()))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"service": "bff", "status": "ok", "version": "0.1.0"}
