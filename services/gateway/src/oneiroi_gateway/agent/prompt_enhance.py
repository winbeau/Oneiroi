import json
from typing import Annotated

import httpx
from pydantic import BaseModel, ConfigDict, Field

from oneiroi_gateway.agent.protocol import (
    AgentProviderError,
    ProviderErrorCode,
)

ENHANCE_INSTRUCTIONS = """You are a short-video prompt engineer. Given a user's video
generation prompt, return exactly one JSON object with two keys:
- "prompt": an improved prompt (keep the user's language when it is clearly intentional)
that preserves the subject and intent, and adds concrete visual detail, camera motion,
lighting, pacing, and a clear sense of temporal progression suitable for a 1-15 second
clip. Keep it under 50000 characters.
- "negativePrompt": a concise comma-separated list of artifacts to avoid (flicker, warping,
identity drift, deformed hands, etc.). Empty string when nothing applies.
Do not add markdown fences, explanations, or any text outside the JSON object."""

ENHANCE_MAX_OUTPUT_TOKENS = 4_096

TITLE_INSTRUCTIONS = """You name a video-creation conversation. Given the user's first prompt,
return exactly one JSON object with one key:
- "title": a concise Chinese title of at most 18 characters that captures the subject and
intent of the video the user wants to create. No quotes, no markdown, no punctuation runs.
Do not add markdown fences, explanations, or any text outside the JSON object."""

TITLE_MAX_OUTPUT_TOKENS = 64


class PromptEnhanceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    prompt: Annotated[str, Field(min_length=1, max_length=50_000)]
    negative_prompt: Annotated[
        str | None, Field(default=None, max_length=50_000, alias="negativePrompt")
    ] = None


class PromptEnhanceResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    prompt: Annotated[str, Field(min_length=1, max_length=50_000)]
    negative_prompt: Annotated[
        str | None, Field(default=None, max_length=50_000, alias="negativePrompt")
    ] = None


class TitleSummarizeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    prompt: Annotated[str, Field(min_length=1, max_length=50_000)]


class TitleSummarizeResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    title: Annotated[str, Field(min_length=1, max_length=100)]


class PromptEnhancer:
    """Single-turn prompt enhancement through a DeepSeek chat-completions endpoint.

    The base URL and API key come from dedicated environment variables
    (ONEIROI_GATEWAY_PROMPT_ENHANCE_*), which the operator fills in on the deployment host.
    """

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str = "deepseek-chat",
        title_model: str | None = None,
        timeout_seconds: float = 45.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.title_model = title_model or model
        self.timeout_seconds = timeout_seconds
        self._transport = transport

    async def enhance(self, request: PromptEnhanceRequest) -> PromptEnhanceResponse:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": ENHANCE_INSTRUCTIONS},
                {"role": "user", "content": request.prompt},
            ],
            "temperature": 0.7,
            "max_tokens": ENHANCE_MAX_OUTPUT_TOKENS,
            "response_format": {"type": "json_object"},
            "stream": False,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        try:
            async with httpx.AsyncClient(
                transport=self._transport,
                timeout=self.timeout_seconds,
                trust_env=False,
            ) as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    json=payload,
                    headers=headers,
                )
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise AgentProviderError(ProviderErrorCode.PROVIDER_UNAVAILABLE) from exc
        if response.status_code in {401, 403}:
            raise AgentProviderError(ProviderErrorCode.AUTH_FAILED)
        if response.status_code == 429:
            raise AgentProviderError(ProviderErrorCode.RATE_LIMITED)
        if response.status_code >= 400:
            raise AgentProviderError(ProviderErrorCode.PROVIDER_UNAVAILABLE)
        try:
            data = response.json()
            content = data["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise AgentProviderError(ProviderErrorCode.OUTPUT_INVALID) from exc
        return self._parse(str(content))

    async def summarize_title(self, request: TitleSummarizeRequest) -> TitleSummarizeResponse:
        """Fast single-turn conversation-title summary through the same DeepSeek endpoint."""
        payload = {
            "model": self.title_model,
            "messages": [
                {"role": "system", "content": TITLE_INSTRUCTIONS},
                {"role": "user", "content": request.prompt},
            ],
            "temperature": 0.3,
            "max_tokens": TITLE_MAX_OUTPUT_TOKENS,
            "response_format": {"type": "json_object"},
            "stream": False,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        try:
            async with httpx.AsyncClient(
                transport=self._transport,
                timeout=self.timeout_seconds,
                trust_env=False,
            ) as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    json=payload,
                    headers=headers,
                )
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise AgentProviderError(ProviderErrorCode.PROVIDER_UNAVAILABLE) from exc
        if response.status_code in {401, 403}:
            raise AgentProviderError(ProviderErrorCode.AUTH_FAILED)
        if response.status_code >= 400:
            raise AgentProviderError(ProviderErrorCode.PROVIDER_UNAVAILABLE)
        try:
            data = response.json()
            content = str(data["choices"][0]["message"]["content"])
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise AgentProviderError(ProviderErrorCode.OUTPUT_INVALID) from exc
        title = self._parse_title(content)
        return TitleSummarizeResponse(title=title)

    @staticmethod
    def _parse_title(raw: str) -> str:
        candidate = raw.strip()
        if candidate.startswith("```"):
            lines = candidate.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            candidate = "\n".join(lines).strip()
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError as exc:
            raise AgentProviderError(ProviderErrorCode.OUTPUT_INVALID) from exc
        if not isinstance(payload, dict):
            raise AgentProviderError(ProviderErrorCode.OUTPUT_INVALID)
        title = str(payload.get("title") or "").strip()
        if not title:
            raise AgentProviderError(ProviderErrorCode.OUTPUT_INVALID)
        return title[:100]

    @staticmethod
    def _parse(raw: str) -> PromptEnhanceResponse:
        candidate = raw
        stripped = raw.strip()
        if stripped.startswith("```"):
            lines = stripped.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            candidate = "\n".join(lines).strip()
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError as exc:
            raise AgentProviderError(ProviderErrorCode.OUTPUT_INVALID) from exc
        if not isinstance(payload, dict):
            raise AgentProviderError(ProviderErrorCode.OUTPUT_INVALID)
        prompt = str(payload.get("prompt") or "").strip()
        if not prompt:
            raise AgentProviderError(ProviderErrorCode.OUTPUT_INVALID)
        negative = payload.get("negativePrompt")
        return PromptEnhanceResponse(
            prompt=prompt,
            negative_prompt=str(negative).strip() if negative is not None else None,
        )
