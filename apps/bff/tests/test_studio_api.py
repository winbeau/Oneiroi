import pytest
from httpx import ASGITransport, AsyncClient

from oneiroi_bff.main import create_app as create_bff
from oneiroi_bff.settings import BffSettings
from oneiroi_gateway.main import create_app as create_gateway
from oneiroi_gateway.settings import GatewaySettings


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
async def test_production_bff_requires_cookie_identity_and_ignores_dev_header() -> None:
    gateway = create_gateway(GatewaySettings(environment="production"))
    bff = create_bff(
        BffSettings(environment="production", gateway_base_url="http://gateway"),
        gateway_app=gateway,
    )
    transport = ASGITransport(app=bff)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        missing = await client.get(
            "/v1/conversations",
            headers={"X-Oneiroi-User": "untrusted-header"},
        )
        client.cookies.set("oneiroi_user", "owner-a")
        authenticated = await client.get("/v1/conversations")

    assert missing.status_code == 401
    assert authenticated.status_code == 200


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
