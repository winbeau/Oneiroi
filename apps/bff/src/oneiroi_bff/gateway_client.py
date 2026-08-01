from collections.abc import AsyncIterator

import httpx
from fastapi import FastAPI

from oneiroi_bff.settings import BffSettings


class GatewayClient:
    def __init__(self, settings: BffSettings, gateway_app: FastAPI | None = None) -> None:
        self.settings = settings
        self.gateway_app = gateway_app

    def _client(self) -> httpx.AsyncClient:
        transport = httpx.ASGITransport(app=self.gateway_app) if self.gateway_app else None
        return httpx.AsyncClient(
            transport=transport,
            base_url=str(self.settings.gateway_base_url).rstrip("/"),
            timeout=self.settings.request_timeout_seconds,
            trust_env=False,
        )

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
        async with self._client() as client:
            return await client.request(method, url, content=content, headers=headers)

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
        response = await client.send(request, stream=True)

        async def body() -> AsyncIterator[bytes]:
            try:
                async for chunk in response.aiter_bytes():
                    yield chunk
            finally:
                await response.aclose()
                await client.aclose()

        return response.status_code, dict(response.headers), body()
