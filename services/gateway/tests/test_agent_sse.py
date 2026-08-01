import asyncio

from oneiroi_gateway.agent.sse import iter_sse_events


async def chunks(payload: bytes, sizes: list[int]):
    cursor = 0
    for size in sizes:
        yield payload[cursor : cursor + size]
        cursor += size
    if cursor < len(payload):
        yield payload[cursor:]


def test_sse_parser_handles_fragmentation_crlf_comments_and_multiline_data() -> None:
    async def scenario() -> None:
        payload = (
            b": heartbeat\r\n"
            b"id: event-1\r\n"
            b"event: custom\r\n"
            b"retry: 1200\r\n"
            b'data: {"hello":\r\n'
            b'data: "world"}\r\n\r\n'
            b"data: [DONE]\n\n"
        )
        events = [event async for event in iter_sse_events(chunks(payload, [1, 2, 3, 5, 8, 13]))]
        assert len(events) == 2
        assert events[0].event_id == "event-1"
        assert events[0].event == "custom"
        assert events[0].retry_ms == 1200
        assert events[0].data == '{"hello":\n"world"}'
        assert events[1].data == "[DONE]"

    asyncio.run(scenario())


def test_sse_parser_accepts_standalone_carriage_return_line_endings() -> None:
    async def scenario() -> None:
        payload = b"id: cr-event\rdata: first\rdata: second\r\r"
        events = [event async for event in iter_sse_events(chunks(payload, [4, 7, 11]))]
        assert len(events) == 1
        assert events[0].event_id == "cr-event"
        assert events[0].data == "first\nsecond"

    asyncio.run(scenario())


def test_sse_parser_dispatches_a_final_event_without_trailing_blank_line() -> None:
    async def scenario() -> None:
        events = [event async for event in iter_sse_events(chunks(b"data: final", [2, 4]))]
        assert [event.data for event in events] == ["final"]

    asyncio.run(scenario())
