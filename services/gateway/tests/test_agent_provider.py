import asyncio
import json
from pathlib import Path

import httpx
import pytest

from oneiroi_gateway.agent.fake import FakeAgentProvider
from oneiroi_gateway.agent.openai_responses import OpenAIResponsesProvider
from oneiroi_gateway.agent.protocol import (
    AgentProviderError,
    GeneratedImage,
    ImageGenerationRequest,
    ProviderErrorCode,
    ProviderEventType,
    ProviderRequest,
    ProviderTool,
)

FIXTURES = Path(__file__).parent / "fixtures" / "agent"


@pytest.mark.asyncio
async def test_fake_provider_is_deterministic_and_explicitly_injected() -> None:
    fake = FakeAgentProvider()
    first = [event async for event in fake.stream_response(request())]
    second = [event async for event in fake.stream_response(request())]
    assert first == second
    assert len(fake.requests) == 2
    assert all(item.store is False for item in fake.requests)
    await fake.close()
    assert fake.closed is True


class FragmentedStream(httpx.AsyncByteStream):
    def __init__(self, payload: bytes, sizes: tuple[int, ...] = (1, 2, 5, 13, 29)) -> None:
        self.payload = payload
        self.sizes = sizes
        self.closed = False

    async def __aiter__(self):
        cursor = 0
        for size in self.sizes:
            if cursor >= len(self.payload):
                break
            yield self.payload[cursor : cursor + size]
            cursor += size
        if cursor < len(self.payload):
            yield self.payload[cursor:]

    async def aclose(self) -> None:
        self.closed = True


class BlockingStream(httpx.AsyncByteStream):
    def __init__(self) -> None:
        self.closed = False
        self.wait = asyncio.Event()

    async def __aiter__(self):
        yield (
            b'id: started\ndata: {"type":"response.created","response":{"id":"resp-cancel"}}\n\n'
        )
        await self.wait.wait()

    async def aclose(self) -> None:
        self.closed = True


def fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes().replace(b"\r\n", b"\n")


def provider(
    handler, *, max_retries: int = 0, max_run_seconds: float = 300
) -> OpenAIResponsesProvider:
    return OpenAIResponsesProvider(
        "https://provider.example/v1",
        "test-key",
        model="gpt-5.6-sol",
        max_run_seconds=max_run_seconds,
        max_retries=max_retries,
        max_retry_delay_seconds=0,
        transport=httpx.MockTransport(handler),
    )


def request(*, tools: list[ProviderTool] | None = None) -> ProviderRequest:
    return ProviderRequest(
        model="gpt-5.6-sol",
        instructions="Server-controlled instructions.",
        input_items=[{"role": "user", "content": [{"type": "input_text", "text": "hello"}]}],
        tools=tools or [],
        reasoning_effort="xhigh",
        max_output_tokens=500,
        request_id="run-test",
    )


@pytest.mark.asyncio
async def test_responses_provider_normalizes_text_reasoning_usage_and_deduplicates() -> None:
    captured: dict[str, object] = {}

    async def handler(http_request: httpx.Request) -> httpx.Response:
        captured["path"] = http_request.url.path
        captured["authorization"] = http_request.headers["authorization"]
        captured["payload"] = json.loads(await http_request.aread())
        return httpx.Response(200, stream=FragmentedStream(fixture("text_reasoning_usage.sse")))

    adapter = provider(handler)
    events = [event async for event in adapter.stream_response(request())]
    await adapter.close()

    assert captured["path"] == "/v1/responses"
    assert captured["authorization"] == "Bearer test-key"
    payload = captured["payload"]
    assert isinstance(payload, dict)
    assert payload["store"] is False
    assert payload["stream"] is True
    assert payload["model"] == "gpt-5.6-sol"
    assert payload["reasoning"] == {"effort": "xhigh"}
    assert [
        event.data["delta"] for event in events if event.event_type == ProviderEventType.TEXT_DELTA
    ] == ["Hello ", "world"]
    assert any(event.event_type == ProviderEventType.REASONING_COMPLETED for event in events)
    usage = next(
        event.data for event in events if event.event_type == ProviderEventType.USAGE_COMPLETED
    )
    assert usage == {"inputTokens": 11, "outputTokens": 7, "totalTokens": 18}
    assert events[-1].event_type == ProviderEventType.RESPONSE_COMPLETED


@pytest.mark.asyncio
async def test_sequence_numbers_deduplicate_standard_responses_events() -> None:
    payload = b"".join(
        [
            b'data: {"type":"response.created","sequence_number":1,'
            b'"response":{"id":"resp-sequence"}}\n\n',
            b'data: {"type":"response.output_text.delta","sequence_number":2,"delta":"once"}\n\n',
            b'data: {"type":"response.output_text.delta","sequence_number":2,'
            b'"delta":"duplicate"}\n\n',
            b'data: {"type":"response.completed","sequence_number":3,'
            b'"response":{"id":"resp-sequence","usage":{"input_tokens":1,'
            b'"output_tokens":1,"total_tokens":2}}}\n\n',
        ]
    )

    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=payload)

    adapter = provider(handler)
    events = [event async for event in adapter.stream_response(request())]
    await adapter.close()
    assert [
        event.data["delta"] for event in events if event.event_type == ProviderEventType.TEXT_DELTA
    ] == ["once"]
    usage = next(event for event in events if event.event_type == ProviderEventType.USAGE_COMPLETED)
    completed = next(
        event for event in events if event.event_type == ProviderEventType.RESPONSE_COMPLETED
    )
    assert usage.provider_event_id != completed.provider_event_id


def test_tool_schema_requires_nested_objects_to_be_strict() -> None:
    with pytest.raises(ValueError, match="every object"):
        ProviderTool(
            name="nested",
            description="Nested strictness probe.",
            input_schema={
                "type": "object",
                "properties": {
                    "nested": {
                        "type": "object",
                        "properties": {"value": {"type": "string"}},
                    }
                },
                "required": ["nested"],
                "additionalProperties": False,
            },
        )


@pytest.mark.asyncio
async def test_function_arguments_are_buffered_then_strictly_validated_once() -> None:
    tool = ProviderTool(
        name="echo_probe",
        description="Echo a probe value.",
        input_schema={
            "type": "object",
            "properties": {"value": {"type": "string"}},
            "required": ["value"],
            "additionalProperties": False,
        },
    )

    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=fixture("function_tool.sse"))

    adapter = provider(handler)
    events = [event async for event in adapter.stream_response(request(tools=[tool]))]
    await adapter.close()
    proposed = [event for event in events if event.event_type == ProviderEventType.TOOL_PROPOSED]
    assert len(proposed) == 1
    assert proposed[0].data == {
        "callId": "call-tool",
        "name": "echo_probe",
        "arguments": {"value": "probe"},
        "argumentsJson": '{"value":"probe"}',
    }
    assert (
        len(
            [
                event
                for event in events
                if event.event_type == ProviderEventType.TOOL_ARGUMENTS_DELTA
            ]
        )
        == 2
    )


@pytest.mark.asyncio
async def test_tool_finalization_rejects_late_argument_or_metadata_changes() -> None:
    tool = ProviderTool(
        name="echo_probe",
        description="Echo a probe value.",
        input_schema={
            "type": "object",
            "properties": {"value": {"type": "string"}},
            "required": ["value"],
            "additionalProperties": False,
        },
    )
    conflict = (
        b'id: tool-conflict\ndata: {"type":"response.output_item.done",'
        b'"item":{"id":"item-tool","type":"function_call",'
        b'"call_id":"different-call","name":"echo_probe",'
        b'"arguments":"{\\"value\\":\\"different\\"}"}}\n\n'
    )
    payload = fixture("function_tool.sse").replace(b"id: tool-6\n", conflict + b"id: tool-6\n")

    async def conflict_handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=payload)

    adapter = provider(conflict_handler)
    with pytest.raises(AgentProviderError) as raised:
        _ = [event async for event in adapter.stream_response(request(tools=[tool]))]
    await adapter.close()
    assert raised.value.code == ProviderErrorCode.TOOL_ARGUMENTS_INVALID

    late_delta = (
        b'id: tool-late-delta\ndata: {"type":"response.function_call_arguments.delta",'
        b'"item_id":"item-tool","delta":" "}\n\n'
    )
    payload = fixture("function_tool.sse").replace(b"id: tool-6\n", late_delta + b"id: tool-6\n")

    async def late_delta_handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=payload)

    adapter = provider(late_delta_handler)
    with pytest.raises(AgentProviderError) as raised:
        _ = [event async for event in adapter.stream_response(request(tools=[tool]))]
    await adapter.close()
    assert raised.value.code == ProviderErrorCode.TOOL_ARGUMENTS_INVALID


@pytest.mark.asyncio
async def test_oversized_tool_argument_stream_is_rejected_before_buffering_unbounded_data() -> None:
    tool = ProviderTool(
        name="echo_probe",
        description="Echo a probe value.",
        input_schema={
            "type": "object",
            "properties": {"value": {"type": "string"}},
            "required": ["value"],
            "additionalProperties": False,
        },
    )
    payload = b"".join(
        [
            b'data: {"type":"response.output_item.added","item":'
            b'{"id":"large-tool","type":"function_call",'
            b'"call_id":"large-call","name":"echo_probe","arguments":""}}\n\n',
            b'data: {"type":"response.function_call_arguments.delta",'
            b'"item_id":"large-tool","delta":"',
            b"x" * (64 * 1024 + 1),
            b'"}\n\n',
        ]
    )

    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=payload)

    adapter = provider(handler)
    with pytest.raises(AgentProviderError) as raised:
        _ = [event async for event in adapter.stream_response(request(tools=[tool]))]
    await adapter.close()
    assert raised.value.code == ProviderErrorCode.TOOL_ARGUMENTS_INVALID


@pytest.mark.asyncio
async def test_malformed_or_extra_tool_arguments_are_rejected() -> None:
    tool = ProviderTool(
        name="echo_probe",
        description="Echo a probe value.",
        input_schema={
            "type": "object",
            "properties": {"value": {"type": "string"}},
            "required": ["value"],
            "additionalProperties": False,
        },
    )
    payload = fixture("function_tool.sse").replace(
        b'{\\"value\\":\\"probe\\"}',
        b'{\\"value\\":\\"probe\\",\\"extra\\":true}',
    )

    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=payload)

    adapter = provider(handler)
    with pytest.raises(AgentProviderError) as raised:
        _ = [event async for event in adapter.stream_response(request(tools=[tool]))]
    await adapter.close()
    assert raised.value.code == ProviderErrorCode.TOOL_ARGUMENTS_INVALID


@pytest.mark.asyncio
async def test_interrupted_stream_fails_without_fabricating_completion() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=fixture("interrupted.sse"))

    adapter = provider(handler)
    seen = []
    with pytest.raises(AgentProviderError) as raised:
        async for event in adapter.stream_response(request()):
            seen.append(event)
    await adapter.close()
    assert raised.value.code == ProviderErrorCode.STREAM_INTERRUPTED
    assert all(event.event_type != ProviderEventType.RESPONSE_COMPLETED for event in seen)


@pytest.mark.asyncio
async def test_provider_failure_event_is_sanitized() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=fixture("failed.sse"))

    adapter = provider(handler)
    events = [event async for event in adapter.stream_response(request())]
    await adapter.close()
    failed = next(
        event for event in events if event.event_type == ProviderEventType.RESPONSE_FAILED
    )
    assert failed.data == {"code": "AGENT_PROVIDER_UNAVAILABLE"}
    assert "sensitive provider detail" not in str(events)


@pytest.mark.asyncio
async def test_http_errors_are_mapped_retried_before_stream_and_redacted() -> None:
    calls = 0

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(503, text="secret upstream body")
        return httpx.Response(200, content=fixture("text_reasoning_usage.sse"))

    adapter = provider(handler, max_retries=1)
    events = [event async for event in adapter.stream_response(request())]
    await adapter.close()
    assert calls == 2
    assert events[-1].event_type == ProviderEventType.RESPONSE_COMPLETED

    async def unauthorized(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="key test-key is invalid")

    adapter = provider(unauthorized)
    with pytest.raises(AgentProviderError) as raised:
        _ = [event async for event in adapter.stream_response(request())]
    await adapter.close()
    assert raised.value.code == ProviderErrorCode.AUTH_FAILED
    assert "test-key" not in str(raised.value)


@pytest.mark.asyncio
async def test_image_success_is_normalized_without_exposing_raw_validation_errors() -> None:
    captured: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(200, json={"id": "img-1", "data": [{"b64_json": "iVBORw0KGgo="}]})

    adapter = provider(handler)
    result = await adapter.generate_image(
        ImageGenerationRequest(
            model="image-model",
            prompt="gray square",
            request_id="image-success",
            size="1024x1024",
        )
    )
    await adapter.close()
    assert result.images[0].base64_data == "iVBORw0KGgo="
    assert result.response_id == "img-1"
    assert captured["model"] == "image-model"
    assert captured["size"] == "1024x1024"
    assert captured["prompt"] == "gray square"


@pytest.mark.asyncio
async def test_generated_image_resolution_is_bounded_and_origin_locked() -> None:
    tiny_png = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x04\x00\x00\x00\xb5\x1c\x0c\x02\x00\x00\x00\x0bIDATx\xdac\x64\xf8"
        b"\x0f\x00\x01\x05\x01\x01'\x18\xe3f\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        if request.url.path.endswith("/redirect"):
            return httpx.Response(302, headers={"Location": "http://127.0.0.1/private"})
        return httpx.Response(200, headers={"Content-Type": "image/png"}, content=tiny_png)

    adapter = provider(handler)
    inline = await adapter.resolve_generated_image(
        GeneratedImage(
            base64Data=(
                "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8A"
                "AQUBAScY42YAAAAASUVORK5CYII="
            ),
            mediaType="image/png",
        ),
        max_bytes=1024,
    )
    assert inline.content == tiny_png
    assert requests == []

    file_result = await adapter.resolve_generated_image(
        GeneratedImage(fileId="file-safe_1"), max_bytes=1024
    )
    assert file_result.content == tiny_png
    assert requests[-1] == "https://provider.example/v1/files/file-safe_1/content"

    url_result = await adapter.resolve_generated_image(
        GeneratedImage(url="https://provider.example/v1/generated/1"), max_bytes=1024
    )
    assert url_result.media_type == "image/png"
    assert requests[-1] == "https://provider.example/v1/generated/1"

    with pytest.raises(AgentProviderError) as external:
        await adapter.resolve_generated_image(
            GeneratedImage(url="https://cdn.example/image.png"), max_bytes=1024
        )
    assert external.value.code is ProviderErrorCode.OUTPUT_INVALID
    with pytest.raises(AgentProviderError) as redirect:
        await adapter.resolve_generated_image(
            GeneratedImage(url="https://provider.example/v1/redirect"), max_bytes=1024
        )
    assert redirect.value.code is ProviderErrorCode.OUTPUT_INVALID
    with pytest.raises(AgentProviderError) as oversized:
        await adapter.resolve_generated_image(GeneratedImage(fileId="file-safe_1"), max_bytes=16)
    assert oversized.value.code is ProviderErrorCode.OUTPUT_INVALID
    await adapter.close()


@pytest.mark.asyncio
async def test_image_file_id_and_url_modes_are_normalized() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"id": "img-ref", "data": [{"url": "https://provider.example/image/1"}]},
        )

    adapter = provider(handler)
    result = await adapter.generate_image(
        ImageGenerationRequest(
            model="image-model",
            prompt="gray square",
            request_id="image-reference",
        )
    )
    await adapter.close()
    assert result.images[0].url == "https://provider.example/image/1"
    assert result.images[0].media_type == "image/png"


@pytest.mark.asyncio
async def test_long_retry_after_and_image_failures_are_not_automatically_replayed() -> None:
    calls = 0

    async def rate_limited(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(429, headers={"Retry-After": "30"})

    adapter = provider(rate_limited, max_retries=3)
    with pytest.raises(AgentProviderError) as raised:
        _ = [event async for event in adapter.stream_response(request())]
    await adapter.close()
    assert raised.value.code == ProviderErrorCode.RATE_LIMITED
    assert calls == 1

    calls = 0
    adapter = provider(rate_limited, max_retries=3)
    with pytest.raises(AgentProviderError):
        await adapter.generate_image(
            ImageGenerationRequest(
                model="image-model",
                prompt="gray square",
                request_id="image-idempotency-not-provided",
            )
        )
    await adapter.close()
    assert calls == 1


@pytest.mark.asyncio
async def test_total_run_deadline_includes_connection_and_response_headers() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(1)
        return httpx.Response(200, content=fixture("text_reasoning_usage.sse"))

    adapter = provider(handler, max_run_seconds=0.02)
    with pytest.raises(AgentProviderError) as raised:
        _ = [event async for event in adapter.stream_response(request())]
    assert raised.value.code == ProviderErrorCode.STREAM_INTERRUPTED
    await adapter.close()


@pytest.mark.asyncio
async def test_total_run_deadline_closes_a_continuously_open_stream() -> None:
    stream = BlockingStream()

    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=stream)

    adapter = provider(handler, max_run_seconds=0.02)
    events = adapter.stream_response(request())
    assert (await anext(events)).event_type == ProviderEventType.RESPONSE_STARTED
    with pytest.raises(AgentProviderError) as raised:
        await anext(events)
    assert raised.value.code == ProviderErrorCode.STREAM_INTERRUPTED
    assert stream.closed is True
    await adapter.close()


@pytest.mark.asyncio
async def test_cancellation_closes_the_stream_transport() -> None:
    stream = BlockingStream()

    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=stream)

    adapter = provider(handler)
    events = adapter.stream_response(request())
    first = await anext(events)
    assert first.event_type == ProviderEventType.RESPONSE_STARTED
    pending = asyncio.create_task(anext(events))
    await asyncio.sleep(0)
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending
    assert stream.closed is True
    await adapter.close()
