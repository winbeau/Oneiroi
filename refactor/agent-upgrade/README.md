# Oneiroi GPT Agent 增强升级主计划

> 设计基线：参考 `gpt-tmp/config.toml`，结合当前 Oneiroi 的 React、Pi BFF、H100 Gateway、PostgreSQL、Asset、Job 与 SSE 边界。本文只定义升级方案，不表示 GPT Agent 已上线。

## 1. 目标

把当前前端本地 `buildSuggestion()` 升级为服务端、可恢复、可审计的创作 Agent，使用户可以在同一个 Conversation 中完成：

1. 用自然语言整理视频创意和镜头提示词；
2. 让 GPT 分析当前 draft、已选首尾帧和用户素材；
3. 获得结构化 prompt、negative prompt、镜头和生成参数建议；
4. 经用户确认后生成参考图片并进入素材库；
5. 经用户确认后把图片设为首帧/尾帧或提交视频生成任务；
6. 查看工具执行、审批、错误、重试和结果，不暴露模型内部思维链。

## 2. 参考配置审计

`gpt-tmp/config.toml` 已明确：

- provider：OpenAI-compatible；
- transport contract：Responses API；
- model：`gpt-5.6-sol`；
- reasoning effort：`xhigh`；
- 自定义 `base_url`；
- 支持 WebSocket；
- `disable_response_storage=true`；
- 需要服务端 OpenAI credential。

但 `gpt-tmp/` 没有提供：

- Responses API 实际请求/事件示例；
- tool schema；
- 图片生成模型或 `image_generation` 工具配置；
- 图片返回是 base64、URL 还是 artifact ID；
- 错误码、限流和 usage contract；
- 可执行 Agent runtime。

因此升级必须先做 capability probe，不能仅凭配置文件断言图片生成已经可用。

`gpt-tmp/auth.json` 是明文凭据文件，不得提交、复制到前端、记录到日志或写入计划文档。正式实施时应迁移到受限环境配置并轮换当前明文凭据。

## 3. 当前 Oneiroi 基线

### 可复用

- Cloudflare Access、稳定 owner 映射和 Pi→H100 服务断言；
- BFF 显式路由 allowlist、CSRF 和请求体限制；
- Gateway 的 Conversation、Asset、Job、PostgreSQL 和 owner 隔离；
- Job durable event、SSE、`Last-Event-ID` 和 snapshot；
- 图片上传校验、素材授权下载和受控 storage；
- OpenAPI→TypeScript DTO、TanStack Query 和 Zustand draft；
- 当前 AgentPanel 已有“建议后用户确认采用”的正确交互原则。

### 缺口

- Conversation 目前只有标题，没有 Agent thread/message；
- AgentPanel 只是浏览器本地模板；
- 没有模型 provider、tool registry、run loop、审批和 usage；
- compute session event 仍有进程内历史实现，不能直接复制给 Agent；
- BFF 尚无 Agent API 显式路由；
- Asset 缺 Agent/image provenance；
- 生产 runtime 仍冻结在旧 release，本计划不能自动激活到生产。

## 4. 核心架构决策

### 4.1 第一阶段把 AgentRuntime 放在 Gateway

推荐先在 `services/gateway` 内增加 Agent 应用域，而不是让浏览器、Pi BFF 或新服务直接调用模型。

原因：

- Gateway 已拥有可信 owner 上下文；
- 可在进程内复用 Conversation、Asset、Job 服务，不需要暴露内部通用 API；
- 模型工具不能绕过 owner 校验；
- BFF 继续保持薄代理和显式 allowlist；
- 少一个服务、密钥和断点，最适合第一版。

当 Agent 并发或独立伸缩需求出现后，可按已定义的 repository/provider contract 拆成独立内部服务，但不作为首版前置条件。

### 4.2 浏览器不得直连 GPT provider

```text
Browser
  │ same-origin HTTPS + Access session
  ▼
Pi BFF
  │ explicit /v1/agent/* allowlist + owner service assertion
  ▼
H100 Gateway
  ├─ AgentRouter
  ├─ AgentRuntime
  ├─ ToolRegistry / ApprovalPolicy
  ├─ OpenAIResponsesProvider ── HTTPS/WSS ── GPT provider
  ├─ Conversation / Asset / Job services
  └─ PostgreSQL Agent events and state
```

API key 只存在于 Gateway 的受限 runtime 配置。任何模型输出都视为不可信数据，必须经过 schema、owner、工具策略和资源限制校验。

### 4.3 本地 PostgreSQL 是 canonical state

因为参考配置关闭 provider response storage：

- 不依赖 provider 保存 conversation；
- 不把 `previous_response_id` 作为唯一恢复依据；
- 每次 run 从本地 thread/message/summary 构造上下文；
- provider response ID 只保存为诊断字段；
- Gateway restart 后从本地 run、tool call、approval 和 event 恢复。

## 5. Agent 操作模型

Agent 不是拥有任意权限的自动化脚本，而是受控创作编排器。

| 能力 | 默认策略 | 说明 |
|---|---|---|
| 读取当前 draft 和 Conversation | 自动 | 只读取当前 owner 资源 |
| 列出/读取素材元数据 | 自动 | 不暴露 storage path |
| 分析用户选中的图片 | 自动但限量 | 只能读取 owner 授权 asset |
| 生成 prompt/draft 建议 | 自动产生 proposal | 不直接改 Zustand draft |
| 采用 draft patch | 用户确认 | 前端显示字段 diff |
| 生成参考图片 | 每次审批 | 有外部成本并创建资产 |
| 设为首帧/尾帧 | 用户确认 | 采用已生成 asset ID |
| 创建视频 Job | 每次审批 | 有 GPU 成本，复用 JobService |
| 取消视频 Job | 每次审批 | 有破坏性结果 |
| 重试视频 Job | 每次审批 | 可能再次产生 GPU 成本 |
| 删除素材、执行 shell、SQL、任意 HTTP | 禁止 | 首版不注册这些工具 |

详细设计见 [`02-runtime-tools.md`](./02-runtime-tools.md)。

## 6. 用户级工作流

### 6.1 提示词增强

1. 用户输入创意；
2. Agent 读取当前 draft 和选中素材元数据；
3. GPT 返回结构化 prompt patch、理由和风险提示；
4. UI 显示 diff；
5. 用户选择全部采用、部分采用或保留原文。

### 6.2 图片理解

1. 用户显式选择最多 N 张已有图片；
2. Gateway 完成 owner 校验并读取受控文件；
3. 图片以受限多模态输入发送给 provider；
4. Agent 返回构图、主体、运动连续性和首尾帧建议；
5. 不把图片中的文字或指令当作系统指令。

### 6.3 参考图片生成

1. Agent 提出 `generate_reference_image` tool call；
2. UI 显示 prompt、数量、尺寸/比例和成本提示；
3. 用户批准；
4. provider 返回图片；
5. Gateway 校验、规范化并通过 ArtifactService 写入 owner 素材库；
6. UI 提供“设为首帧”“设为尾帧”“继续修改”。

### 6.4 视频任务编排

1. Agent 根据已确认 draft 和 asset ID 提出视频任务；
2. UI 显示最终参数和 GPU 成本动作；
3. 用户批准；
4. AgentRuntime 调用现有 JobService；
5. Agent 只引用真实 Job snapshot/event，不模拟成功。

## 7. 模块计划索引

1. [`01-provider-and-configuration.md`](./01-provider-and-configuration.md)：Responses API、模型能力、配置、transport 和错误规范。
2. [`02-runtime-tools.md`](./02-runtime-tools.md)：AgentRuntime、工具注册、审批、预算和执行循环。
3. [`03-data-api-events.md`](./03-data-api-events.md)：PostgreSQL 模型、API、状态机、durable SSE 和恢复。
4. [`04-image-generation.md`](./04-image-generation.md)：图片理解、图片生成、资产化、校验和 provenance。
5. [`05-frontend-experience.md`](./05-frontend-experience.md)：AgentPanel、流式 UI、diff、审批和移动端交互。
6. [`06-security-operations.md`](./06-security-operations.md)：身份、secret、prompt injection、配额、审计和运维。
7. [`07-implementation-rollout.md`](./07-implementation-rollout.md)：分阶段实施、验收、发布和回滚。

## 8. 推荐阶段

| 阶段 | 结果 | 预计 |
|---|---|---:|
| A. 凭据与 capability probe | 验证 Responses、stream、tool、图片和 usage contract | 0.5–1.5 天 |
| B. 只读提示词助手 | GPT 文本增强、结构化 draft proposal、无写工具 | 2–3 天 |
| C. Durable Agent runtime | thread/run/message/event、SSE、取消、恢复 | 3–5 天 |
| D. 工具与审批 | 只读工具、一次性审批、幂等 write/costly 工具 | 2–4 天 |
| E. 图片生成 | 生成图片校验、素材化、首尾帧采用 | 2–4 天 |
| F. 视频任务编排 | 经审批创建/cancel/retry Job | 2–3 天 |
| G. Canary 与运维 | 配额、成本、告警、双用户和故障恢复 | 2–4 天 |

首个可用“GPT 提示词增强器”约 3–5 个工作日；完整 Agent + 图片 + Job 编排约 12–20 个工作日。若 provider 的图片或 WebSocket contract 与标准 Responses API 不兼容，增加约 3–5 天不确定性。

## 9. 总体验收门

- 浏览器和 BFF 日志中不存在 provider API key；
- 所有 Agent 资源按 owner 隔离，跨 owner 统一返回 404；
- 文本、工具参数、工具结果和图片均经过 schema 与大小限制；
- Agent 不执行未注册工具，不具有 shell、SQL、文件路径或任意网络权限；
- costly/destructive 操作必须用户审批，审批绑定 owner、run、call 和参数哈希；
- 页面刷新和 Gateway restart 后 run 可从 snapshot + event cursor 恢复；
- 图片生成结果进入现有 Asset 域，校验 hash、尺寸、媒体类型和 owner；
- Agent 不显示原始 chain-of-thought，只显示状态、结论和可审计工具步骤；
- provider 不可用时不影响 Conversation、Asset 和现有 Job API；
- feature flag 关闭后恢复当前本地提示词整理器或明确显示 Agent 暂不可用；
- 真实双用户和真实 provider canary 通过后才允许生产放量。

## 10. 明确不做

- 不让模型执行 shell、Python、SQL、SSH 或任意 URL 抓取；
- 不让模型直接访问 gpu-server 内部端口；
- 不让 Agent 绕过 JobService 自建 GPU scheduler/Runner；
- 不自动删除用户素材；
- 不在首版做多 Agent 群体协作、长期自主任务或无人审批的付费生成；
- 不依赖 provider 保存的隐式 conversation state；
- 不把模型“说任务成功了”视为真实 Job 成功。
