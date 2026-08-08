from collections.abc import AsyncIterator

import httpx
from fastapi import FastAPI

from oneiroi_bff.settings import BffSettings


class GatewayClient:
    def __init__(self, settings: BffSettings, gateway_app: FastAPI | None = None) -> None:
        self.settings = settings
        self.gateway_app = gateway_app
        self._pool: httpx.AsyncClient | None = None

    def _client(self) -> httpx.AsyncClient:
        if self._pool is None or self._pool.is_closed:
            transport = httpx.ASGITransport(app=self.gateway_app) if self.gateway_app else None
            self._pool = httpx.AsyncClient(
                transport=transport,
                base_url=str(self.settings.gateway_base_url).rstrip("/"),
                timeout=self.settings.request_timeout_seconds,
                trust_env=False,
                limits=httpx.Limits(
                    max_connections=64,
                    max_keepalive_connections=32,
                    # Keep the tunnel TCP connection alive for minutes so the first
                    # request does not repeatedly pay the proxy/Tunnel handshake cost.
                    keepalive_expiry=300,
                ),
            )
        return self._pool

    async def _reset(self) -> None:
        client = self._pool
        self._pool = None
        if client is not None:
            await client.aclose()

    async def request(
        self,
        method: str,
        path: str,
        *,
        content: bytes,
        headers: dict[str, str],
        query: str,
    ) -> httpx.Response:
        url = f"{path}?{query}" if query else path
        client = self._client()
        try:
            return await client.request(method, url, content=content, headers=headers)
        except httpx.TransportError:
            # A dropped pooled connection must not poison subsequent requests.
            await self._reset()
            raise

    async def stream(
        self,
        method: str,
        path: str,
        *,
        headers: dict[str, str],
        query: str,
    ) -> tuple[int, dict[str, str], AsyncIterator[bytes]]:
        client = self._client()
        url = f"{path}?{query}" if query else path
        request = client.build_request(method, url, headers=headers)
        try:
            response = await client.send(request, stream=True)
        except httpx.TransportError:
            await self._reset()
            raise

        async def body() -> AsyncIterator[bytes]:
            try:
                async for chunk in response.aiter_bytes():
                    yield chunk
            except httpx.TransportError:
                pass
            finally:
                await response.aclose()

        return response.status_code, dict(response.headers), body()

    async def aclose(self) -> None:
        await self._reset()
