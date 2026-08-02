import asyncio
import json

import pytest
from httpx import ASGITransport, AsyncClient

from oneiroi_bff.main import create_app as create_bff
from oneiroi_bff.settings import BffSettings
from oneiroi_gateway.agent.fake import FakeAgentProvider
from oneiroi_gateway.agent.protocol import ProviderEvent, ProviderEventType
from oneiroi_gateway.main import create_app as create_gateway
from oneiroi_gateway.settings import GatewaySettings


@pytest.mark.asyncio
async def test_bff_explicitly_proxies_agent_routes_and_sse_headers() -> None:
    payload = json.dumps(
        {"text": "proposal", "draftProposal": {"prompt": "improved prompt"}},
        separators=(",", ":"),
    )
    provider = FakeAgentProvider(
        events=[
            ProviderEvent(
                event_type=ProviderEventType.TEXT_DELTA,
                data={"delta": payload},
            ),
            ProviderEvent(event_type=ProviderEventType.RESPONSE_COMPLETED),
        ]
    )
    gateway = create_gateway(GatewaySettings(_env_file=None), agent_provider=provider)
    bff = create_bff(
        BffSettings(_env_file=None, gateway_base_url="http://gateway"), gateway_app=gateway
    )
    async with AsyncClient(transport=ASGITransport(app=bff), base_url="http://test") as client:
        headers = {"X-Oneiroi-User": "owner-a"}
        capabilities = await client.get("/v1/agent/capabilities", headers=headers)
        conversation = await client.post(
            "/v1/conversations", headers=headers, json={"title": "BFF Agent"}
        )
        run = await client.post(
            "/v1/agent/runs",
            headers={**headers, "Idempotency-Key": "bff-agent-1"},
            json={
                "conversationId": conversation.json()["id"],
                "message": "improve",
                "draftSnapshot": {"prompt": "lake"},
            },
        )
        for _ in range(100):
            snapshot = await client.get(f"/v1/agent/runs/{run.json()['id']}", headers=headers)
            if snapshot.json()["status"] == "completed":
                break
            await asyncio.sleep(0.01)
        thread = await client.get(
            f"/v1/conversations/{conversation.json()['id']}/agent/thread",
            headers=headers,
        )
        messages = await client.get(
            f"/v1/agent/threads/{thread.json()['id']}/messages", headers=headers
        )
        events = await client.get(f"/v1/agent/runs/{run.json()['id']}/events", headers=headers)
        approve = await client.post(
            "/v1/agent/tool-calls/missing/approve", headers=headers, json={}
        )
        reject = await client.post("/v1/agent/tool-calls/missing/reject", headers=headers, json={})
        unknown = await client.get("/v1/agent/not-allowlisted", headers=headers)

    assert capabilities.status_code == 200
    assert run.status_code == 202
    assert snapshot.json()["status"] == "completed"
    assert messages.json()[-1]["content"]["draftProposal"]["prompt"] == "improved prompt"
    assert events.headers["cache-control"] == "no-cache"
    assert events.headers["x-accel-buffering"] == "no"
    assert approve.status_code == reject.status_code == 404
    assert unknown.status_code == 404
    await gateway.state.agent_runtime.close()


@pytest.mark.asyncio
async def test_bff_uses_smaller_agent_json_limit() -> None:
    bff = create_bff(
        BffSettings(
            _env_file=None,
            gateway_base_url="http://127.0.0.1:9",
            max_upload_bytes=1024,
            max_agent_json_bytes=8,
        )
    )
    async with AsyncClient(transport=ASGITransport(app=bff), base_url="http://test") as client:
        response = await client.post(
            "/v1/agent/runs",
            headers={"Idempotency-Key": "body-limit"},
            content=b"123456789",
        )
        approval = await client.post(
            "/v1/agent/tool-calls/test/approve",
            content=b"123456789",
        )
    assert response.status_code == approval.status_code == 413
