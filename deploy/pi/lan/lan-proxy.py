#!/usr/bin/env python3
import argparse
import asyncio
import contextlib
import signal
import ssl

BUFFER_BYTES = 64 * 1024
CONNECT_TIMEOUT_SECONDS = 10
IDLE_TIMEOUT_SECONDS = 120
MAX_CONNECTIONS = 64


async def copy_stream(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while chunk := await asyncio.wait_for(
            reader.read(BUFFER_BYTES), timeout=IDLE_TIMEOUT_SECONDS
        ):
            writer.write(chunk)
            await asyncio.wait_for(writer.drain(), timeout=CONNECT_TIMEOUT_SECONDS)
    except (TimeoutError, ConnectionError, OSError, ssl.SSLError):
        pass
    finally:
        with contextlib.suppress(ConnectionError, NotImplementedError, OSError, RuntimeError):
            writer.write_eof()


async def close_writer(writer: asyncio.StreamWriter) -> None:
    writer.close()
    with contextlib.suppress(
        TimeoutError, ConnectionError, OSError, RuntimeError, ssl.SSLError
    ):
        await asyncio.wait_for(writer.wait_closed(), timeout=CONNECT_TIMEOUT_SECONDS)


async def serve_connection(
    client_reader: asyncio.StreamReader,
    client_writer: asyncio.StreamWriter,
    *,
    target_host: str,
    target_port: int,
    capacity: asyncio.Semaphore,
) -> None:
    try:
        await asyncio.wait_for(capacity.acquire(), timeout=1)
    except TimeoutError:
        await close_writer(client_writer)
        return

    upstream_writer: asyncio.StreamWriter | None = None
    try:
        upstream_reader, upstream_writer = await asyncio.wait_for(
            asyncio.open_connection(target_host, target_port, limit=BUFFER_BYTES),
            timeout=CONNECT_TIMEOUT_SECONDS,
        )
        upload = asyncio.create_task(copy_stream(client_reader, upstream_writer))
        download = asyncio.create_task(copy_stream(upstream_reader, client_writer))
        await asyncio.gather(upload, download)
    except (TimeoutError, ConnectionError, OSError):
        pass
    finally:
        if upstream_writer is not None:
            await close_writer(upstream_writer)
        await close_writer(client_writer)
        capacity.release()


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("listen_host")
    parser.add_argument("listen_port", type=int)
    parser.add_argument("target_host")
    parser.add_argument("target_port", type=int)
    parser.add_argument("--certificate")
    parser.add_argument("--private-key")
    args = parser.parse_args()

    tls_context = None
    if bool(args.certificate) != bool(args.private_key):
        parser.error("--certificate and --private-key must be provided together")
    if args.certificate:
        tls_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        tls_context.minimum_version = ssl.TLSVersion.TLSv1_2
        tls_context.load_cert_chain(args.certificate, args.private_key)

    capacity = asyncio.Semaphore(MAX_CONNECTIONS)
    server = await asyncio.start_server(
        lambda reader, writer: serve_connection(
            reader,
            writer,
            target_host=args.target_host,
            target_port=args.target_port,
            capacity=capacity,
        ),
        args.listen_host,
        args.listen_port,
        ssl=tls_context,
        ssl_handshake_timeout=CONNECT_TIMEOUT_SECONDS if tls_context else None,
        backlog=128,
        limit=BUFFER_BYTES,
    )

    mode = "TLS" if tls_context else "TCP"
    print(
        f"{mode} proxy listening on {args.listen_host}:{args.listen_port} "
        f"-> {args.target_host}:{args.target_port}",
        flush=True,
    )
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signum, stop.set)
    async with server:
        await stop.wait()


if __name__ == "__main__":
    asyncio.run(main())
