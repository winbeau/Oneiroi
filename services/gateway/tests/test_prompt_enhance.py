import json

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

from oneiroi_gateway.agent.prompt_enhance import (
    PromptEnhancer,
    PromptEnhanceRequest,
    TitleSummarizeRequest,
)
from oneiroi_gateway.agent.protocol import (
    AgentProviderError,
    ProviderErrorCode,
)
from oneiroi_gateway.main import create_app
from oneiroi_gateway.settings import GatewaySettings


def _completions_body(content: str) -> dict[str, object]:
    return {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": content}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
    }


def _enhancer(handler, *, api_key: str = "ds-key") -> PromptEnhancer:
    return PromptEnhancer(
        base_url="https://api.deepseek.com",
        api_key=api_key,
        model="deepseek-chat",
        transport=httpx.MockTransport(handler),
    )


async def _enhance(handler, prompt: str = "a cat walking") -> str:
    enhancer = _enhancer(handler)
    result = await enhancer.enhance(
        PromptEnhanceRequest(prompt=prompt, negative_prompt="flicker")
    )
    return result.prompt


@pytest.mark.asyncio
async def test_enhancer_sends_chat_completion_and_parses_json() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/chat/completions"
        assert request.headers["authorization"] == "Bearer ds-key"
        payload = json.loads(request.content)
        assert payload["model"] == "deepseek-chat"
        assert payload["messages"][1]["content"] == "a cat walking"
        assert payload["response_format"] == {"type": "json_object"}
        return httpx.Response(
            200,
            json=_completions_body(
                '{"prompt": "cinematic cat close-up, slow dolly in", "negativePrompt": "flicker"}'
            ),
        )

    result = await _enhance(handler)
    assert result == "cinematic cat close-up, slow dolly in"


@pytest.mark.asyncio
async def test_enhancer_parses_fenced_json() -> None:
    content = (
        "```json\n"
        + json.dumps({"prompt": "warm morning light", "negativePrompt": ""})
        + "\n```"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_completions_body(content))

    result = await _enhance(handler)
    assert result == "warm morning light"


@pytest.mark.asyncio
async def test_enhancer_rejects_invalid_content() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_completions_body("not json at all"))

    enhancer = _enhancer(handler)
    with pytest.raises(AgentProviderError) as exc_info:
        await enhancer.enhance(PromptEnhanceRequest(prompt="a cat"))
    assert exc_info.value.code is ProviderErrorCode.OUTPUT_INVALID


@pytest.mark.asyncio
async def test_enhancer_maps_http_errors() -> None:
    for status, expected in [
        (401, ProviderErrorCode.AUTH_FAILED),
        (429, ProviderErrorCode.RATE_LIMITED),
        (500, ProviderErrorCode.PROVIDER_UNAVAILABLE),
    ]:

        def handler(request: httpx.Request, status: int = status) -> httpx.Response:
            return httpx.Response(status, json={"error": "boom"})

        enhancer = _enhancer(handler)
        with pytest.raises(AgentProviderError) as exc_info:
            await enhancer.enhance(PromptEnhanceRequest(prompt="a cat"))
        assert exc_info.value.code is expected


@pytest.mark.asyncio
async def test_title_summarize_parses_title() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload["model"] == "deepseek-v4-flash"
        assert payload["max_tokens"] <= 64
        return httpx.Response(
            200,
            json=_completions_body('{"title": "雨夜街道漫步"}'),
        )

    enhancer = PromptEnhancer(
        base_url="https://api.deepseek.com",
        api_key="ds-key",
        model="deepseek-chat",
        title_model="deepseek-v4-flash",
        transport=httpx.MockTransport(handler),
    )
    result = await enhancer.summarize_title(
        TitleSummarizeRequest(prompt="a cat walking in rain")
    )
    assert result.title == "雨夜街道漫步"


def _agent_app(tmp_path, *, enhancer_enabled: bool):
    app_settings = GatewaySettings(
        storage_root=tmp_path,
        agent_enabled=False,
        prompt_enhance_enabled=enhancer_enabled,
        prompt_enhance_base_url="https://api.deepseek.com",
        prompt_enhance_api_key="ds-key" if enhancer_enabled else None,
    )
    return create_app(app_settings)


@pytest.mark.asyncio
async def test_prompt_enhance_endpoint_returns_enhanced_prompt(tmp_path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/chat/completions"
        return httpx.Response(
            200,
            json=_completions_body('{"prompt": "enhanced by deepseek", "negativePrompt": ""}'),
        )

    injected = _enhancer(handler)
    app = create_app(
        GatewaySettings(storage_root=tmp_path, agent_enabled=False),
        prompt_enhancer=injected,
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/v1/agent/prompt-enhance",
            json={"prompt": "a cat walking", "negativePrompt": "flicker"},
        )
    assert response.status_code == 200
    assert response.json()["prompt"] == "enhanced by deepseek"
    assert response.json()["negativePrompt"] == ""


@pytest.mark.asyncio
async def test_title_summarize_endpoint_unavailable_without_config(tmp_path) -> None:
    app = _agent_app(tmp_path, enhancer_enabled=False)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/v1/agent/title-summarize",
            json={"prompt": "a cat walking"},
        )
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "AGENT_UNAVAILABLE"
