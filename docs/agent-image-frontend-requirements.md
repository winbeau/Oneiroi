# Agent 图片能力：后端与前端接入说明

> Gateway / Provider / Artifact 能力来自 `gpt-agent` 分支；当前 `apps/web` 已完成能力门控、Run/SSE、审批、候选图与显式草稿应用。本文同时保留接口约束与验收标准。

## 1. 后端已实现

### 1.1 图片理解输入

- `POST /v1/agent/runs` 的 `assetIds` 支持传入最多 4 个当前用户拥有的图片 Asset。
- 只有 `/v1/agent/capabilities` 返回 `imageInput: true` 时，图片才会作为受控 data URL 发送给 Provider。
- Gateway 会校验 owner、Asset 类型、文件边界、真实图片内容和大小；不会向浏览器或 Provider暴露本地存储路径。
- 图片能力关闭或未通过 capability probe 时 fail closed，文本 Agent 不受影响。

请求示例：

```json
{
  "conversationId": "conversation-id",
  "message": "分析这张图片并给出首帧建议",
  "draftSnapshot": {
    "mode": "I2V",
    "prompt": "待完善",
    "ratio": "16:9"
  },
  "assetIds": ["asset-id"],
  "mode": "image-analysis"
}
```

### 1.2 参考图片生成工具

新增受控工具 `generate_reference_image`：

- 风险等级为 `costly`，每次执行前必须由用户审批。
- 每个 run 最多调用一次；一次生成 1–2 张。
- 参数包括：`prompt`、`negativePrompt`、`purpose`、`ratio`、`count`、`referenceAssetIds`。
- `purpose`：`first-frame`、`last-frame`、`style-reference`。
- `ratio`：`16:9`、`9:16`、`1:1`。
- 参考 Asset 必须属于当前用户；需要 `imageInput: true`。
- Provider 可返回 base64、受控 file ID 或同源 HTTPS URL；跨源 URL、重定向和超限内容会被拒绝。

### 1.3 安全 Asset 化

生成结果不会直接写入草稿。Gateway 会先执行：

1. 有界读取和真实图片解码；
2. 动画、超大像素、超长边和非法内容拒绝；
3. EXIF 方向处理、metadata 清理、统一转为 PNG；
4. SHA-256、稳定 Asset ID、`.partial` 临时文件和原子替换；
5. owner-bound Asset 持久化、并发幂等和崩溃恢复。

`GET /v1/assets` 返回的生成 Asset 新增可选 `provenance`：

```json
{
  "sourceType": "agent-image",
  "agentRunId": "agent-run-id",
  "toolCallId": "agent-tool-id",
  "outputIndex": 0,
  "provider": "openai-responses",
  "model": "image-model",
  "promptSha256": "<64位sha256>",
  "purpose": "first-frame",
  "ratio": "16:9",
  "providerResponseId": "provider-response-id",
  "safetyOutcome": "accepted",
  "createdAt": "2026-01-01T00:00:00Z"
}
```

前端不得展示或尝试还原 `promptSha256`，也不得依赖 provider 内部 ID。

### 1.4 持久化预算和恢复

- Provider 事件数和 active run 时间跨审批、恢复及多轮工具 continuation 累计，不会在恢复时重置。
- 运行中断时，已安全注册的部分图片会保留；未注册的 `.partial` 或孤立文件会清理。
- costly 工具结果未知时不会自动重放，返回恢复错误，避免重复计费。

## 2. 前端必须实现

### 2.1 能力门控

页面初始化调用：

```http
GET /v1/agent/capabilities
```

按以下字段控制 UI：

- `available`: Agent 总开关；为 `false` 时隐藏或禁用 Agent 入口。
- `imageInput`: 是否允许向 run 提交 `assetIds`。
- `imageGeneration`: 是否展示“生成参考图”相关提示和结果区域。
- `toolsEnabled` 以及 `tools[].name === "generate_reference_image"`: 是否允许进入生成图审批流程。

任何字段为 `false` 都不得由前端自行绕过。

### 2.2 Run 与 SSE

1. 使用 `POST /v1/agent/runs` 创建 run，并提供唯一 `Idempotency-Key`。
2. 使用 `GET /v1/agent/runs/{runId}/events` 订阅 SSE。
3. 断线重连时发送最后成功处理的 `Last-Event-ID`。
4. 至少处理：
   - `agent.run.started` / `agent.run.resumed`
   - `agent.message.delta`
   - `agent.tool.proposed`
   - `agent.approval.required`
   - `agent.tool.started`
   - `agent.tool.completed` / `agent.tool.failed`
   - `agent.run.completed` / `agent.run.failed` / `agent.run.cancelled`
5. SSE payload、Agent 文本、错误文本和 Asset title 均按不可信文本渲染，不得作为 HTML 注入。

### 2.3 审批交互

收到 `agent.approval.required` 后展示确认卡片：

- 工具名固定显示为“生成参考图片”。
- 展示 `purpose`、`ratio`、`count`、是否包含参考图和 `estimatedCost`。
- 不允许用户在审批弹窗中修改参数；需要修改时应拒绝本次调用，再发新消息。
- 同意：`POST /v1/agent/tool-calls/{toolCallId}/approve`。
- 拒绝：`POST /v1/agent/tool-calls/{toolCallId}/reject`。
- body 只发送可选 `note`、`clientVersion`，不要发送替换后的 arguments。
- 对 `expired`、重复决定和网络重试显示幂等结果，不重复触发生成。

### 2.4 生成结果展示与草稿应用

`agent.tool.completed` 的 tool result 包含：

```json
{
  "assets": [
    {
      "id": "asset-id",
      "type": "image",
      "title": "Agent 首帧参考图",
      "mediaType": "image/png",
      "width": 1536,
      "height": 1024
    }
  ],
  "partial": false,
  "errorCode": null
}
```

前端要求：

- 生成结果作为候选 Asset 卡片展示，并可通过现有 Asset 接口刷新详情。
- `partial: true` 时保留并展示成功图片，同时给出部分失败提示。
- **不得自动修改 draft**。
- 每张图提供显式操作：
  - “设为首帧” → 更新本地 draft 的 `firstFrameAssetId`；
  - “设为尾帧” → 更新本地 draft 的 `lastFrameAssetId`；
  - “仅保存” → 不修改 draft；
  - `style-reference` 默认仅保存，除非产品另行定义用途。
- 用户确认应用前，不得自动创建视频 Job。

### 2.5 错误和状态

至少区分：

- `AGENT_IMAGE_NOT_SUPPORTED`：当前模型或配置不支持图片输入/生成。
- `AGENT_IMAGE_INVALID` / `AGENT_IMAGE_REJECTED`：Provider 图片未通过安全处理。
- `AGENT_RESOURCE_NOT_FOUND`：Asset 不存在或不属于当前用户。
- `AGENT_RUN_TIMEOUT`：累计 active-time 用尽。
- `AGENT_TOOL_RECOVERY_REQUIRED`：中断后的 costly 工具结果未知，禁止自动重试。
- `AGENT_OUTPUT_INVALID`：Provider 输出或累计事件预算无效。

错误提示应提供“重新发起新 run”操作；对 recovery-required 和 costly 操作不得自动重试。

## 3. 前端验收标准

- `apps/web` 只通过同源 BFF `/v1/agent/*` 和现有 `/v1/assets*` 接口访问后端。
- capability 为 false 时对应控件不可操作。
- 审批参数只读，批准和拒绝均可恢复到 SSE 流程。
- 生成 1 张、2 张、部分成功和失败状态均有明确 UI。
- 生成图片不会自动替换草稿，也不会自动提交视频任务。
- SSE 重连不重复消息、不重复审批、不重复插入 Asset 卡片。
- 所有外部文本均安全转义；UI 不展示 provider URL、本地路径、credential、raw provider event 或 hidden reasoning。

## 4. 当前前端实现

- `apps/web/src/features/agent/hooks.ts`：capabilities、Run、线程消息、审批/拒绝、取消和带 `Last-Event-ID` 的 SSE 重连。
- `apps/web/src/features/create/agent-panel.tsx`：Oneiroi 助理对话、只读审批卡、错误分级、草稿建议和生成图片候选。
- `apps/web/src/lib/demo-api.ts`：仓库外部服务不可用时使用显式 Demo 模式模拟 Agent、审批与候选图，不影响生产请求路径。
- `apps/web/e2e/studio.spec.ts`：覆盖“审批前不改草稿、批准后只产生候选、用户点击后才设为首帧”。

生产环境仍默认关闭 Agent 与图片工具；只有 Gateway capabilities 明确返回可用时，前端才展示对应入口。
