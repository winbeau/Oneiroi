import asyncio
import base64
import binascii
from collections.abc import AsyncIterator
from datetime import UTC, datetime

from oneiroi_common.agent import AgentProbeRecord, CapabilitySupport
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
    ResolvedGeneratedImage,
)

_TINY_PNG_BASE64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


class FakeAgentProvider:
    def __init__(
        self,
        *,
        events: list[ProviderEvent] | None = None,
        event_batches: list[list[ProviderEvent]] | None = None,
        image_generation: bool = False,
        image_input: bool = False,
        generated_images: list[GeneratedImage] | None = None,
        image_payloads: dict[str, bytes] | None = None,
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
        self.image_input = image_input
        self.generated_images = generated_images or [
            GeneratedImage(base64Data=_TINY_PNG_BASE64, mediaType="image/png")
        ]
        self.image_payloads = image_payloads or {}
        self.delay_seconds = delay_seconds
        self.requests: list[ProviderRequest] = []
        self.image_requests: list[ImageGenerationRequest] = []
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
        self.image_requests.append(request)
        if not self.image_generation:
            raise AgentProviderError(ProviderErrorCode.IMAGE_NOT_SUPPORTED)
        return ImageGenerationResult(
            images=self.generated_images,
            response_id=f"fake-image-{request.request_id}",
            event_count=1,
        )

    async def resolve_generated_image(
        self, image: GeneratedImage, *, max_bytes: int
    ) -> ResolvedGeneratedImage:
        if image.base64_data is not None:
            try:
                content = base64.b64decode(image.base64_data, validate=True)
            except (binascii.Error, ValueError):
                raise AgentProviderError(ProviderErrorCode.OUTPUT_INVALID) from None
        else:
            key = image.file_id or image.url
            if key is None or key not in self.image_payloads:
                raise AgentProviderError(ProviderErrorCode.OUTPUT_INVALID)
            content = self.image_payloads[key]
        if not content or len(content) > max_bytes:
            raise AgentProviderError(ProviderErrorCode.OUTPUT_INVALID)
        return ResolvedGeneratedImage(content=content, media_type=image.media_type)

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
