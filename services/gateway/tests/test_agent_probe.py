import asyncio
import json
import os
import stat
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from oneiroi_common.agent import CapabilitySupport
from oneiroi_gateway.agent.capability_probe import probe_provider, write_probe_record
from oneiroi_gateway.agent.endpoint import provider_endpoint_hash
from oneiroi_gateway.agent.protocol import (
    AgentProviderError,
    GeneratedImage,
    ImageGenerationRequest,
    ImageGenerationResult,
    ProviderErrorCode,
    ProviderEvent,
    ProviderEventType,
    ProviderRequest,
)


class ProbeProvider:
    async def stream_response(self, request: ProviderRequest) -> AsyncIterator[ProviderEvent]:
        if request.request_id == "probe-error-format":
            raise AgentProviderError(
                ProviderErrorCode.OUTPUT_INVALID,
                status_code=404,
                request_id="safe-request-id",
            )
        events = [ProviderEvent(event_type=ProviderEventType.RESPONSE_STARTED)]
        if request.request_id == "probe-text":
            events.extend(
                [
                    ProviderEvent(
                        event_type=ProviderEventType.TEXT_DELTA,
                        data={"delta": "ready"},
                    ),
                    ProviderEvent(
                        event_type=ProviderEventType.USAGE_COMPLETED,
                        data={"inputTokens": 1, "outputTokens": 1, "totalTokens": 2},
                    ),
                ]
            )
        elif request.request_id == "probe-tool":
            events.append(
                ProviderEvent(
                    event_type=ProviderEventType.TOOL_PROPOSED,
                    data={
                        "callId": "call-probe",
                        "name": "echo_probe",
                        "arguments": {"value": "probe"},
                        "argumentsJson": '{"value":"probe"}',
                    },
                )
            )
        events.append(ProviderEvent(event_type=ProviderEventType.RESPONSE_COMPLETED))
        for event in events:
            yield event

    async def generate_image(self, request: ImageGenerationRequest) -> ImageGenerationResult:
        return ImageGenerationResult(
            images=[GeneratedImage(base64_data="iVBORw0KGgo=", media_type="image/png")],
            response_id=f"image-{request.request_id}",
        )

    async def probe(self, **_kwargs):  # pragma: no cover - the standalone probe is under test
        raise AssertionError("unexpected nested probe")

    async def close(self) -> None:
        return None


@pytest.mark.asyncio
async def test_probe_covers_text_tool_continuation_images_usage_and_errors() -> None:
    record = await probe_provider(
        ProbeProvider(),
        model="gpt-5.6-sol",
        endpoint_hash=provider_endpoint_hash("https://provider.example/v1"),
        reasoning_effort="xhigh",
        image_model="image-model",
        websocket_declared=True,
        include_image_generation=True,
        probe_error_format=True,
    )
    assert record.text == CapabilitySupport.SUPPORTED
    assert record.streaming == CapabilitySupport.SUPPORTED
    assert record.function_tools == CapabilitySupport.SUPPORTED
    assert record.tool_continuation == CapabilitySupport.SUPPORTED
    assert record.image_input == CapabilitySupport.SUPPORTED
    assert record.image_generation == CapabilitySupport.SUPPORTED
    assert record.usage == CapabilitySupport.SUPPORTED
    assert record.error_format == CapabilitySupport.SUPPORTED
    assert record.transport == ["sse"]
    assert record.websocket_declared is True
    assert record.websocket_verified is False


def test_probe_record_is_atomic_restricted_and_contains_no_credentials(tmp_path: Path) -> None:
    capability = asyncio.run(
        probe_provider(
            ProbeProvider(),
            model="gpt-5.6-sol",
            endpoint_hash=provider_endpoint_hash("https://provider.example/v1"),
        )
    )
    output = tmp_path / "capabilities.json"
    write_probe_record(output, capability)
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["testedModel"] == "gpt-5.6-sol"
    assert "apiKey" not in payload
    assert "baseUrl" not in payload
    assert "Authorization" not in output.read_text(encoding="utf-8")
    if os.name != "nt":
        assert stat.S_IMODE(output.stat().st_mode) == 0o600
    assert not (tmp_path / ".capabilities.json.partial").exists()
