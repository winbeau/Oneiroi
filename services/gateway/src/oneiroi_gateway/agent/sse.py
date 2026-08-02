import codecs
from collections.abc import AsyncIterable, AsyncIterator
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ServerSentEvent:
    data: str
    event: str | None = None
    event_id: str | None = None
    retry_ms: int | None = None


async def iter_sse_events(
    chunks: AsyncIterable[bytes], *, max_event_chars: int = 32 * 1024 * 1024
) -> AsyncIterator[ServerSentEvent]:
    decoder = codecs.getincrementaldecoder("utf-8")("strict")
    text_buffer = ""
    data_lines: list[str] = []
    event_type: str | None = None
    event_id: str | None = None
    retry_ms: int | None = None
    event_chars = 0

    def consume_line(line: str) -> ServerSentEvent | None:
        nonlocal data_lines, event_type, event_id, retry_ms, event_chars
        if line == "":
            if not data_lines and event_type is None and event_id is None and retry_ms is None:
                return None
            event = ServerSentEvent(
                data="\n".join(data_lines),
                event=event_type,
                event_id=event_id,
                retry_ms=retry_ms,
            )
            data_lines = []
            event_type = None
            event_id = None
            retry_ms = None
            event_chars = 0
            return event
        if line.startswith(":"):
            return None
        field, separator, value = line.partition(":")
        if separator and value.startswith(" "):
            value = value[1:]
        if field == "data":
            event_chars += len(value)
            if event_chars > max_event_chars:
                raise ValueError("SSE_EVENT_TOO_LARGE")
            data_lines.append(value)
        elif field == "event":
            event_type = value
        elif field == "id" and "\x00" not in value:
            event_id = value
        elif field == "retry" and value.isdigit():
            retry_ms = int(value)
        return None

    def pop_line(*, final: bool = False) -> str | None:
        nonlocal text_buffer
        for index, character in enumerate(text_buffer):
            if character == "\n":
                line = text_buffer[:index]
                text_buffer = text_buffer[index + 1 :]
                return line
            if character == "\r":
                if index + 1 == len(text_buffer) and not final:
                    return None
                consumed = 2 if text_buffer[index + 1 : index + 2] == "\n" else 1
                line = text_buffer[:index]
                text_buffer = text_buffer[index + consumed :]
                return line
        return None

    async for chunk in chunks:
        if not chunk:
            continue
        text_buffer += decoder.decode(chunk)
        while (line := pop_line()) is not None:
            if event := consume_line(line):
                yield event
        if len(text_buffer) + event_chars > max_event_chars:
            raise ValueError("SSE_EVENT_TOO_LARGE")

    text_buffer += decoder.decode(b"", final=True)
    while (line := pop_line(final=True)) is not None:
        if event := consume_line(line):
            yield event
    if text_buffer and (event := consume_line(text_buffer)):
        yield event
    if event := consume_line(""):
        yield event
