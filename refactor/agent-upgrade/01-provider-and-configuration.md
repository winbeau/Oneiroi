# 模块 1：GPT Provider 与配置

## 1. 目标

为 Gateway 提供稳定、可测试、可替换的 Responses API adapter，支持：

- `gpt-5.6-sol` 文本和多模态输入；
- streaming response；
- function/tool call；
- 可选图片生成；
- `store=false`；
- reasoning effort 配置；
- 自定义 OpenAI-compatible `base_url`；
- provider 错误归一化和 usage 采集。

## 2. 参考配置映射

建议映射为 Gateway 配置，而不是运行时读取 `gpt-tmp/config.toml`：

| 参考项 | Gateway 配置 |
|---|---|
| `model_provider=OpenAI` | `ONEIROI_GATEWAY_AGENT_PROVIDER=openai-responses` |
| `model=gpt-5.6-sol` | `ONEIROI_GATEWAY_AGENT_MODEL=gpt-5.6-sol` |
| `review_model` | 首版不单独调用；保留 `AGENT_REVIEW_MODEL` 可选项 |
| `model_reasoning_effort=xhigh` | `ONEIROI_GATEWAY_AGENT_REASONING_EFFORT=xhigh` |
| `disable_response_storage=true` | `ONEIROI_GATEWAY_AGENT_STORE=false` |
| `base_url` | `ONEIROI_GATEWAY_AGENT_BASE_URL=<provider>/v1` |
| `wire_api=responses` | adapter 固定使用 `/responses` contract |
| `supports_websockets=true` | capability probe 后才启用 WSS |

新增配置建议：

```text
ONEIROI_GATEWAY_AGENT_ENABLED=false
ONEIROI_GATEWAY_AGENT_API_KEY=<secret>
ONEIROI_GATEWAY_AGENT_CONNECT_TIMEOUT_SECONDS=10
ONEIROI_GATEWAY_AGENT_STREAM_TIMEOUT_SECONDS=180
ONEIROI_GATEWAY_AGENT_MAX_RUN_SECONDS=300
ONEIROI_GATEWAY_AGENT_MAX_OUTPUT_TOKENS=4000
ONEIROI_GATEWAY_AGENT_MAX_INPUT_IMAGES=4
ONEIROI_GATEWAY_AGENT_MAX_IMAGE_BYTES=20971520
ONEIROI_GATEWAY_AGENT_TRANSPORT=sse
ONEIROI_GATEWAY_AGENT_IMAGE_ENABLED=false
ONEIROI_GATEWAY_AGENT_IMAGE_MODEL=
ONEIROI_GATEWAY_AGENT_IMAGE_MODE=responses-tool
```

约束：

- `agent_enabled=true` 时必须存在 API key、HTTPS base URL 和 model；
- 生产默认关闭；
- API key 使用 `SecretStr`，`repr`、异常和 health response 不得输出；
- base URL 不接受浏览器或请求体覆盖；
- image model/tool 必须经过 probe 才标记为 available。

## 3. Provider 接口

建议新增：

```text
services/gateway/src/oneiroi_gateway/agent/
  provider.py
  openai_responses.py
  protocol.py
  capability_probe.py
```

核心协议：

```python
class AgentProvider(Protocol):
    async def stream_response(self, request: ProviderRequest) -> AsyncIterator[ProviderEvent]: ...
    async def generate_image(self, request: ImageGenerationRequest) -> ImageGenerationResult: ...
    async def probe(self) -> ProviderCapabilities: ...
    async def close(self) -> None: ...
```

`ProviderRequest` 只包含规范化字段：

- model；
- system instructions；
- local canonical input items；
- tool definitions；
- reasoning effort；
- output token limit；
- `store=false`；
- request/run correlation metadata。

Runtime 不直接依赖 provider 原始 JSON。

## 4. Transport 决策

### 首版使用 HTTP SSE

虽然参考配置声明支持 WebSocket，首版仍推荐 SSE：

- 当前 Gateway 已依赖 `httpx`；
- 与 FastAPI 生命周期和测试工具一致；
- 易于录制碎片化 event fixture；
- 自定义 OpenAI-compatible endpoint 对 SSE 的兼容性通常更清晰；
- 可以先完成 correctness，再比较 WSS 延迟。

### WebSocket 作为第二 transport

只有 probe 验证以下条件后才启用：

- 鉴权 header/子协议明确；
- reconnect 语义明确；
- tool result continuation contract 明确；
- provider 在中断后不会重复执行 tool call；
- heartbeat 和 idle timeout 可测试。

`AGENT_TRANSPORT=websocket` 必须是显式 canary 配置，不根据单个请求切换。

## 5. Responses API 请求规则

首版必须满足：

- 请求固定 `store: false`；
- system instructions 由版本化 server prompt 提供；
- 用户输入、asset caption 和 tool result 作为不可信 content；
- 不把用户文本拼进 system prompt；
- tools 来自 server registry，模型不能新增工具；
- tool schema 使用严格 JSON Schema，拒绝额外字段；
- 不依赖 `previous_response_id` 恢复 thread；
- provider response ID 只作为诊断信息；
- 每轮从 PostgreSQL message/summary 构造最小上下文。

## 6. Event 归一化

Provider adapter 把外部事件转成内部事件：

```text
response.started
text.delta
text.completed
tool.arguments.delta
tool.proposed
image.started
image.completed
usage.completed
response.completed
response.failed
```

规则：

- JSON 参数可能跨多个 chunk，必须增量缓冲后一次 schema validate；
- 重复 provider event ID 必须去重；
- 未知事件记录计数但不直接转发给浏览器；
- 原始 payload 只在受控 debug 环境短期保留，生产默认不落库；
- 文本 delta 可以进入 durable Agent event，但 snapshot 以最终 message 为准。

## 7. Reasoning 与用户输出

- 可以向 provider 请求 `xhigh` reasoning；
- 不向用户展示隐藏 chain-of-thought；
- 若 provider 返回 reasoning summary，只保留经过长度限制的“操作说明”；
- UI 展示“正在分析素材”“正在生成方案”等状态，而非内部推理 token；
- assistant 最终输出采用结构化 response schema，避免从自然语言解析关键参数。

建议最终 schema：

```json
{
  "reply": "面向用户的简洁说明",
  "draftProposal": {
    "prompt": "...",
    "negativePrompt": "...",
    "ratio": "16:9",
    "resolution": "720p",
    "duration": 5,
    "seed": 42
  },
  "rationale": ["..."],
  "warnings": ["..."]
}
```

所有字段再由 Oneiroi Pydantic contract 校验。

## 8. 图片能力探测

`gpt-tmp` 没有图片模型信息，实施阶段 A 必须验证：

1. `gpt-5.6-sol` 是否接受 image input；
2. 是否支持 Responses `image_generation` tool；
3. 图片生成是否需要独立 model；
4. 返回 base64、URL、file ID 还是 mixed content；
5. 支持的 ratio/size/format/quality；
6. image tool 是否支持 streaming partial；
7. usage 如何计量；
8. safety refusal 和限流错误格式。

Probe 结果写成不含 secret 的 capability fixture，例如：

```json
{
  "text": true,
  "streaming": true,
  "functionTools": true,
  "imageInput": true,
  "imageGeneration": false,
  "transport": ["sse"],
  "testedModel": "gpt-5.6-sol"
}
```

生产功能只依据 probe/capability，不依据前端文案。

## 9. 错误归一化

建议 Agent 错误码：

- `AGENT_NOT_CONFIGURED`
- `AGENT_PROVIDER_UNAVAILABLE`
- `AGENT_AUTH_FAILED`
- `AGENT_RATE_LIMITED`
- `AGENT_CONTEXT_TOO_LARGE`
- `AGENT_OUTPUT_INVALID`
- `AGENT_STREAM_INTERRUPTED`
- `AGENT_TOOL_ARGUMENTS_INVALID`
- `AGENT_IMAGE_NOT_SUPPORTED`
- `AGENT_IMAGE_REJECTED`
- `AGENT_BUDGET_EXCEEDED`
- `AGENT_CANCELLED`

重试策略：

- connect timeout、502/503：有界指数退避；
- 429：尊重 `Retry-After`，不在同一个请求内无限等待；
- 401/403：不重试，配置错误；
- 已出现 costly tool call 后不自动重放整轮；
- 图片生成的自动重试必须有稳定 idempotency key 或默认禁用。

## 10. 测试与完成门

- MockTransport 覆盖正常文本、碎片 JSON、工具调用、未知事件和中途断流；
- 验证每个请求都为 `store=false`；
- 验证 key/base URL 不进入日志和异常；
- 验证 malformed tool args 被拒绝且工具未执行；
- 验证 provider 断流后 run 进入可恢复失败，不伪造完成；
- 验证 image capability 不存在时文本 Agent 仍可用；
- 真实 provider canary 记录 model、transport、请求时间和 capability，不记录完整 credential。
