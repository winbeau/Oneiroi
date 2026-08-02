import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime

from oneiroi_common.agent import AgentProbeRecord, CapabilitySupport
from oneiroi_gateway.agent.endpoint import provider_endpoint_hash
from oneiroi_gateway.agent.protocol import (
    GeneratedImage,
    ImageGenerationRequest,
    ImageGenerationResult,
    ProviderEvent,
    ProviderEventType,
    ProviderRequest,
)


class FakeAgentProvider:
    def __init__(
        self,
        *,
        events: list[ProviderEvent] | None = None,
        event_batches: list[list[ProviderEvent]] | None = None,
        image_generation: bool = False,
        delay_seconds: float = 0,
    ) -> None:
        self.events = events or [
            ProviderEvent(
                event_type=ProviderEventType.RESPONSE_STARTED, response_id="fake-response"
            ),
            ProviderEvent(
                event_type=ProviderEventType.TEXT_DELTA,
                response_id="fake-response",
                data={"delta": "deterministic fake response"},
            ),
            ProviderEvent(
                event_type=ProviderEventType.TEXT_COMPLETED,
                response_id="fake-response",
                data={"text": "deterministic fake response"},
            ),
            ProviderEvent(
                event_type=ProviderEventType.USAGE_COMPLETED,
                response_id="fake-response",
                data={"inputTokens": 8, "outputTokens": 4, "totalTokens": 12},
            ),
            ProviderEvent(
                event_type=ProviderEventType.RESPONSE_COMPLETED, response_id="fake-response"
            ),
        ]
        self.event_batches = event_batches
        self.image_generation = image_generation
        self.delay_seconds = delay_seconds
        self.requests: list[ProviderRequest] = []
        self.closed = False

    async def stream_response(self, request: ProviderRequest) -> AsyncIterator[ProviderEvent]:
        self.requests.append(request)
        if self.event_batches is not None:
            index = len(self.requests) - 1
            if index >= len(self.event_batches):
                raise RuntimeError("FAKE_PROVIDER_BATCHES_EXHAUSTED")
            events = self.event_batches[index]
        else:
            events = self.events
        for event in events:
            if self.delay_seconds:
                await asyncio.sleep(self.delay_seconds)
            yield event

    async def generate_image(self, request: ImageGenerationRequest) -> ImageGenerationResult:
        if not self.image_generation:
            from oneiroi_gateway.agent.protocol import AgentProviderError, ProviderErrorCode

            raise AgentProviderError(ProviderErrorCode.IMAGE_NOT_SUPPORTED)
        return ImageGenerationResult(
            images=[GeneratedImage(base64_data="iVBORw0KGgo=", media_type="image/png")],
            response_id=f"fake-image-{request.request_id}",
        )

    async def probe(
        self,
        *,
        include_image_generation: bool = False,
        probe_error_format: bool = False,
    ) -> AgentProbeRecord:
        del probe_error_format
        return AgentProbeRecord(
            endpoint_hash=provider_endpoint_hash("https://fake.invalid/v1"),
            tested_model="fake-model",
            text=CapabilitySupport.SUPPORTED,
            streaming=CapabilitySupport.SUPPORTED,
            function_tools=CapabilitySupport.SUPPORTED,
            tool_continuation=CapabilitySupport.SUPPORTED,
            image_input=CapabilitySupport.SUPPORTED,
            image_generation=(
                CapabilitySupport.SUPPORTED
                if include_image_generation and self.image_generation
                else CapabilitySupport.NOT_PROBED
            ),
            usage=CapabilitySupport.SUPPORTED,
            transport=["sse"],
            probed_at=datetime.now(UTC),
        )

    async def close(self) -> None:
        self.closed = True
