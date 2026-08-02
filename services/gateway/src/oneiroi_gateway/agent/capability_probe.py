import argparse
import asyncio
import json
import os
import sys
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from oneiroi_common.agent import AgentProbeRecord, CapabilitySupport
from oneiroi_gateway.agent.openai_responses import OpenAIResponsesProvider
from oneiroi_gateway.agent.protocol import (
    AgentProvider,
    AgentProviderError,
    ImageGenerationRequest,
    ProviderErrorCode,
    ProviderEvent,
    ProviderEventType,
    ProviderRequest,
    ProviderTool,
)
from oneiroi_gateway.settings import GatewaySettings

_TINY_PNG_DATA_URL = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Y9ZKZsAAAAASUVORK5CYII="
)


async def probe_provider(
    provider: AgentProvider,
    *,
    model: str,
    endpoint_hash: str,
    reasoning_effort: str = "xhigh",
    image_model: str | None = None,
    websocket_declared: bool = False,
    include_image_generation: bool = False,
    probe_error_format: bool = False,
) -> AgentProbeRecord:
    base_request = {
        "model": model,
        "reasoning_effort": reasoning_effort,
        "max_output_tokens": 256,
        "store": False,
    }
    text_events = await _collect(
        provider.stream_response(
            ProviderRequest(
                **base_request,
                instructions="Reply with the single word ready. Do not call tools.",
                input_items=[
                    {"role": "user", "content": [{"type": "input_text", "text": "probe"}]}
                ],
                request_id="probe-text",
            )
        )
    )
    text_supported = _completed(text_events)
    streaming_supported = any(
        event.event_type == ProviderEventType.TEXT_DELTA for event in text_events
    )
    usage_supported = any(
        event.event_type == ProviderEventType.USAGE_COMPLETED for event in text_events
    )

    function_tools = CapabilitySupport.UNSUPPORTED
    tool_continuation = CapabilitySupport.UNSUPPORTED
    tool = ProviderTool(
        name="echo_probe",
        description="Return the supplied probe value.",
        input_schema={
            "type": "object",
            "properties": {"value": {"type": "string", "const": "probe"}},
            "required": ["value"],
            "additionalProperties": False,
        },
    )
    first_tool_events = await _collect(
        provider.stream_response(
            ProviderRequest(
                **base_request,
                instructions="Call echo_probe exactly once with value probe.",
                input_items=[
                    {
                        "role": "user",
                        "content": [{"type": "input_text", "text": "Use the probe tool."}],
                    }
                ],
                tools=[tool],
                tool_choice={"type": "function", "name": "echo_probe"},
                request_id="probe-tool",
            )
        )
    )
    proposed = next(
        (
            event
            for event in first_tool_events
            if event.event_type == ProviderEventType.TOOL_PROPOSED
        ),
        None,
    )
    if proposed is not None:
        function_tools = CapabilitySupport.SUPPORTED
        call_id = cast(str, proposed.data["callId"])
        arguments_json = cast(str, proposed.data["argumentsJson"])
        continuation_events = await _collect(
            provider.stream_response(
                ProviderRequest(
                    **base_request,
                    instructions=(
                        "Use the probe tool result, then reply with the single word continued."
                    ),
                    input_items=[
                        {
                            "role": "user",
                            "content": [{"type": "input_text", "text": "Use the probe tool."}],
                        },
                        {
                            "type": "function_call",
                            "call_id": call_id,
                            "name": "echo_probe",
                            "arguments": arguments_json,
                        },
                        {
                            "type": "function_call_output",
                            "call_id": call_id,
                            "output": json.dumps({"value": "probe", "ok": True}),
                        },
                    ],
                    tools=[tool],
                    request_id="probe-tool-continuation",
                )
            )
        )
        if _completed(continuation_events):
            tool_continuation = CapabilitySupport.SUPPORTED

    image_input = CapabilitySupport.NOT_PROBED
    try:
        image_events = await _collect(
            provider.stream_response(
                ProviderRequest(
                    **base_request,
                    instructions=(
                        "Describe whether the supplied image is readable in one short sentence."
                    ),
                    input_items=[
                        {
                            "role": "user",
                            "content": [
                                {"type": "input_text", "text": "Inspect this one-pixel image."},
                                {"type": "input_image", "image_url": _TINY_PNG_DATA_URL},
                            ],
                        }
                    ],
                    request_id="probe-image-input",
                )
            )
        )
        image_input = (
            CapabilitySupport.SUPPORTED
            if _completed(image_events)
            else CapabilitySupport.UNSUPPORTED
        )
    except AgentProviderError as exc:
        if exc.code in {ProviderErrorCode.AUTH_FAILED, ProviderErrorCode.RATE_LIMITED}:
            raise
        image_input = CapabilitySupport.UNSUPPORTED

    image_generation = CapabilitySupport.NOT_PROBED
    if include_image_generation:
        try:
            result = await provider.generate_image(
                ImageGenerationRequest(
                    model=image_model or model,
                    prompt="A plain neutral gray square used only for a capability probe.",
                    request_id="probe-image-generation",
                )
            )
            image_generation = (
                CapabilitySupport.SUPPORTED if result.images else CapabilitySupport.UNSUPPORTED
            )
        except AgentProviderError as exc:
            if exc.code in {ProviderErrorCode.AUTH_FAILED, ProviderErrorCode.RATE_LIMITED}:
                raise
            image_generation = CapabilitySupport.UNSUPPORTED

    error_format = CapabilitySupport.NOT_PROBED
    rate_limit_observed = False
    if probe_error_format:
        try:
            await _collect(
                provider.stream_response(
                    ProviderRequest(
                        **(base_request | {"model": f"{model}-oneiroi-invalid-probe"}),
                        instructions=(
                            "This request intentionally probes the normalized error contract."
                        ),
                        input_items=[
                            {
                                "role": "user",
                                "content": [{"type": "input_text", "text": "probe error"}],
                            }
                        ],
                        request_id="probe-error-format",
                    )
                )
            )
            error_format = CapabilitySupport.UNSUPPORTED
        except AgentProviderError as exc:
            error_format = (
                CapabilitySupport.SUPPORTED
                if exc.status_code is not None
                else CapabilitySupport.UNSUPPORTED
            )
            rate_limit_observed = exc.code == ProviderErrorCode.RATE_LIMITED

    return AgentProbeRecord(
        endpoint_hash=endpoint_hash,
        tested_model=model,
        image_model=image_model or model,
        text=(CapabilitySupport.SUPPORTED if text_supported else CapabilitySupport.UNSUPPORTED),
        streaming=(
            CapabilitySupport.SUPPORTED if streaming_supported else CapabilitySupport.UNSUPPORTED
        ),
        function_tools=function_tools,
        tool_continuation=tool_continuation,
        image_input=image_input,
        image_generation=image_generation,
        usage=(CapabilitySupport.SUPPORTED if usage_supported else CapabilitySupport.UNSUPPORTED),
        error_format=error_format,
        rate_limit_observed=rate_limit_observed,
        transport=["sse"],
        websocket_declared=websocket_declared,
        websocket_verified=False,
        probed_at=datetime.now(UTC),
    )


async def _collect(events: AsyncIterator[ProviderEvent]) -> list[ProviderEvent]:
    return [event async for event in events]


def _completed(events: list[ProviderEvent]) -> bool:
    return any(event.event_type == ProviderEventType.RESPONSE_COMPLETED for event in events)


def write_probe_record(path: Path, record: AgentProbeRecord) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(f".{path.name}.partial")
    payload = (
        json.dumps(
            record.model_dump(mode="json", by_alias=True),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    partial.unlink(missing_ok=True)
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_NOINHERIT", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    descriptor = os.open(partial, flags, 0o600)
    try:
        if hasattr(os, "fchmod"):
            os.fchmod(descriptor, 0o600)
        output = os.fdopen(descriptor, "w", encoding="utf-8")
        descriptor = -1
        with output:
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
        os.replace(partial, path)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        partial.unlink(missing_ok=True)


async def _run_cli(args: argparse.Namespace) -> int:
    settings = GatewaySettings()
    if not settings.agent_api_key or not settings.agent_base_url or not settings.agent_model:
        print(ProviderErrorCode.NOT_CONFIGURED.value, file=sys.stderr)
        return 2
    output = args.output or settings.agent_capability_file
    if output is None:
        print("AGENT_CAPABILITY_FILE_REQUIRED", file=sys.stderr)
        return 2
    provider = OpenAIResponsesProvider(
        settings.agent_base_url,
        settings.agent_api_key.get_secret_value(),
        model=settings.agent_model,
        reasoning_effort=settings.agent_reasoning_effort,
        image_model=settings.agent_image_model or None,
        websocket_declared=settings.agent_provider_websocket_declared,
        connect_timeout_seconds=settings.agent_connect_timeout_seconds,
        stream_timeout_seconds=settings.agent_stream_timeout_seconds,
        max_run_seconds=settings.agent_max_run_seconds,
        max_retries=settings.agent_max_retries,
        max_retry_delay_seconds=settings.agent_max_retry_delay_seconds,
    )
    try:
        record = await provider.probe(
            include_image_generation=args.include_image_generation,
            probe_error_format=args.probe_error_format,
        )
        write_probe_record(output, record)
    except AgentProviderError as exc:
        print(exc.code.value, file=sys.stderr)
        return 1
    finally:
        await provider.close()
    print(f"wrote capability record: {output}")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Probe the configured Responses API provider.")
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--include-image-generation",
        action="store_true",
        help="Explicitly allow the potentially billable image-generation probe.",
    )
    parser.add_argument(
        "--probe-error-format",
        action="store_true",
        help="Send one intentional invalid-model request to inspect normalized errors.",
    )
    args = parser.parse_args()
    raise SystemExit(asyncio.run(_run_cli(args)))


if __name__ == "__main__":
    main()
