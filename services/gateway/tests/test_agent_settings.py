import pytest
from pydantic import ValidationError

from oneiroi_gateway.settings import GatewaySettings


def settings(**overrides: object) -> GatewaySettings:
    return GatewaySettings(_env_file=None, **overrides)


def test_agent_is_disabled_by_default() -> None:
    configured = settings()
    assert configured.agent_enabled is False
    assert configured.agent_store is False
    assert configured.agent_transport == "sse"


def test_enabled_agent_requires_key_https_base_url_and_model() -> None:
    with pytest.raises(ValidationError, match="AGENT_API_KEY"):
        settings(agent_enabled=True, agent_base_url="https://provider.example/v1")
    with pytest.raises(ValidationError, match="AGENT_BASE_URL"):
        settings(agent_enabled=True, agent_api_key="secret")
    with pytest.raises(ValidationError, match="AGENT_MODEL"):
        settings(
            agent_enabled=True,
            agent_api_key="secret",
            agent_base_url="https://provider.example/v1",
            agent_model=" ",
        )


@pytest.mark.parametrize(
    "base_url",
    [
        "http://provider.example/v1",
        "https://user:password@provider.example/v1",
        "https://provider.example/v1?token=secret",
        "https://provider.example/v1#fragment",
    ],
)
def test_agent_base_url_rejects_insecure_or_credentialed_values(base_url: str) -> None:
    with pytest.raises(ValidationError, match="credential-free HTTPS"):
        settings(agent_base_url=base_url)


def test_agent_base_url_rejects_invalid_port() -> None:
    with pytest.raises(ValidationError, match="valid port"):
        settings(agent_base_url="https://provider.example:not-a-port/v1")


def test_agent_key_is_redacted_from_settings_repr() -> None:
    configured = settings(
        agent_enabled=True,
        agent_api_key="redaction-test-key",
        agent_base_url="https://provider.example/v1",
    )
    assert "redaction-test-key" not in repr(configured)
    assert "redaction-test-key" not in str(configured)


def test_websocket_requires_explicit_canary_flag() -> None:
    with pytest.raises(ValidationError, match="WebSocket canary flag"):
        settings(agent_transport="websocket")
    configured = settings(agent_transport="websocket", agent_websocket_enabled=True)
    assert configured.agent_transport == "websocket"


def test_store_cannot_be_enabled() -> None:
    with pytest.raises(ValidationError):
        settings(agent_store=True)


def test_image_flags_require_agent() -> None:
    with pytest.raises(ValidationError, match="Agent image flags"):
        settings(agent_image_enabled=True)
