import json
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from oneiroi_common.agent import AgentProbeRecord, CapabilitySupport
from oneiroi_gateway.agent.endpoint import provider_endpoint_hash
from oneiroi_gateway.main import create_app
from oneiroi_gateway.services.agent_capabilities import AgentCapabilityService
from oneiroi_gateway.settings import GatewaySettings


def settings(**overrides: object) -> GatewaySettings:
    return GatewaySettings(_env_file=None, **overrides)


def write_record(path: Path, **overrides: object) -> None:
    values: dict[str, object] = {
        "endpoint_hash": provider_endpoint_hash("https://provider.example/v1"),
        "tested_model": "gpt-5.6-sol",
        "image_model": "gpt-5.6-sol",
        "text": CapabilitySupport.SUPPORTED,
        "streaming": CapabilitySupport.SUPPORTED,
        "function_tools": CapabilitySupport.SUPPORTED,
        "tool_continuation": CapabilitySupport.SUPPORTED,
        "image_input": CapabilitySupport.SUPPORTED,
        "image_generation": CapabilitySupport.SUPPORTED,
        "usage": CapabilitySupport.SUPPORTED,
        "transport": ["sse"],
        "websocket_declared": True,
        "probed_at": datetime.now(UTC),
    }
    values.update(overrides)
    payload = AgentProbeRecord.model_validate(values)
    path.write_text(json.dumps(payload.model_dump(mode="json", by_alias=True)), encoding="utf-8")
    path.chmod(0o600)


@pytest.mark.asyncio
async def test_capability_endpoint_is_disabled_by_default() -> None:
    app = create_app(settings())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/v1/agent/capabilities")
    assert response.status_code == 200
    assert response.json() == {
        "enabled": False,
        "configured": False,
        "available": False,
        "reasonCode": "AGENT_DISABLED",
        "provider": None,
        "model": None,
        "text": False,
        "streaming": False,
        "functionTools": False,
        "imageInput": False,
        "imageGeneration": False,
        "usage": False,
        "transports": [],
        "websocketDeclared": False,
        "websocketVerified": False,
    }


def test_enabled_agent_fails_closed_without_probe() -> None:
    service = AgentCapabilityService(
        settings(
            agent_enabled=True,
            agent_api_key="secret",
            agent_base_url="https://provider.example/v1",
        )
    )
    response = service.get()
    assert response.available is False
    assert response.reason_code == "AGENT_NOT_PROBED"


def test_probe_controls_image_capabilities(tmp_path: Path) -> None:
    record_path = tmp_path / "agent-capabilities.json"
    write_record(record_path)
    disabled_images = AgentCapabilityService(
        settings(
            agent_enabled=True,
            agent_api_key="secret",
            agent_base_url="https://provider.example/v1",
            agent_capability_file=record_path,
        )
    ).get()
    assert disabled_images.available is True
    assert disabled_images.function_tools is True
    assert disabled_images.image_input is False
    assert disabled_images.image_generation is False

    enabled_images = AgentCapabilityService(
        settings(
            agent_enabled=True,
            agent_api_key="secret",
            agent_base_url="https://provider.example/v1",
            agent_capability_file=record_path,
            agent_image_input_enabled=True,
            agent_image_enabled=True,
        )
    ).get()
    assert enabled_images.image_input is True
    assert enabled_images.image_generation is True


def test_probe_is_bound_to_endpoint_and_image_model(tmp_path: Path) -> None:
    record_path = tmp_path / "agent-capabilities.json"
    write_record(record_path)
    changed_endpoint = settings(
        agent_enabled=True,
        agent_api_key="secret",
        agent_base_url="https://other-provider.example/v1",
        agent_capability_file=record_path,
    )
    assert AgentCapabilityService(changed_endpoint).get().reason_code == "AGENT_PROBE_MISMATCH"

    changed_image_model = settings(
        agent_enabled=True,
        agent_api_key="secret",
        agent_base_url="https://provider.example/v1",
        agent_capability_file=record_path,
        agent_image_enabled=True,
        agent_image_model="different-image-model",
    )
    assert AgentCapabilityService(changed_image_model).get().image_generation is False


def test_insecure_capability_files_fail_closed(tmp_path: Path) -> None:
    record_path = tmp_path / "agent-capabilities.json"
    write_record(record_path)
    record_path.chmod(0o644)
    configured = settings(
        agent_enabled=True,
        agent_api_key="secret",
        agent_base_url="https://provider.example/v1",
        agent_capability_file=record_path,
    )
    assert AgentCapabilityService(configured).get().reason_code == "AGENT_NOT_PROBED"

    record_path.chmod(0o600)
    link_path = tmp_path / "capabilities-link.json"
    link_path.symlink_to(record_path)
    linked = configured.model_copy(update={"agent_capability_file": link_path})
    assert AgentCapabilityService(linked).get().reason_code == "AGENT_NOT_PROBED"


def test_capability_file_must_be_owned_by_the_gateway_user(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    record_path = tmp_path / "agent-capabilities.json"
    write_record(record_path)
    configured = settings(
        agent_enabled=True,
        agent_api_key="secret",
        agent_base_url="https://provider.example/v1",
        agent_capability_file=record_path,
    )
    monkeypatch.setattr(os, "geteuid", lambda: record_path.stat().st_uid + 1)
    assert AgentCapabilityService(configured).get().reason_code == "AGENT_NOT_PROBED"


def test_malformed_or_mismatched_probe_fails_closed(tmp_path: Path) -> None:
    record_path = tmp_path / "agent-capabilities.json"
    record_path.write_text("not-json", encoding="utf-8")
    configured = settings(
        agent_enabled=True,
        agent_api_key="secret",
        agent_base_url="https://provider.example/v1",
        agent_capability_file=record_path,
    )
    assert AgentCapabilityService(configured).get().reason_code == "AGENT_NOT_PROBED"

    write_record(record_path, tested_model="different-model")
    assert AgentCapabilityService(configured).get().reason_code == "AGENT_PROBE_MISMATCH"


def test_declared_websocket_is_not_available_without_verified_probe(tmp_path: Path) -> None:
    record_path = tmp_path / "agent-capabilities.json"
    write_record(record_path)
    configured = settings(
        agent_enabled=True,
        agent_api_key="secret",
        agent_base_url="https://provider.example/v1",
        agent_capability_file=record_path,
        agent_transport="websocket",
        agent_websocket_enabled=True,
    )
    response = AgentCapabilityService(configured).get()
    assert response.available is False
    assert response.websocket_declared is True
    assert response.websocket_verified is False
    assert response.reason_code == "AGENT_TRANSPORT_UNAVAILABLE"
