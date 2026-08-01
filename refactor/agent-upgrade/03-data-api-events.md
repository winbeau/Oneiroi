# 模块 3：数据模型、API 与 Durable Events

## 1. 目标

让 Agent thread、消息、运行、工具、审批和事件在 PostgreSQL 中持久化，并通过 owner 隔离的 API/SSE 支持刷新和 Gateway restart 恢复。

## 2. 数据模型

建议新增 Alembic migration `0002_agent_runtime.py`。

### `agent_threads`

| 字段 | 说明 |
|---|---|
| `id` | `agent-thread-*` |
| `owner_id` | 稳定 owner，索引 |
| `conversation_id` | FK conversations，首版建议 unique |
| `status` | active/archived |
| `summary_text` | 本地压缩摘要，可空 |
| `summary_cursor` | 已摘要到的 message 序号 |
| `prompt_version` | system prompt 版本 |
| `created_at/updated_at` | 时间 |

首版一个 Conversation 对应一个 Agent thread。未来需要多方案分支时再放开一对多。

### `agent_messages`

| 字段 | 说明 |
|---|---|
| `id` | message ID |
| `owner_id/thread_id/run_id` | 隔离与关联 |
| `sequence` | thread 内严格递增 |
| `role` | user/assistant/tool/system_summary |
| `content_json` | 文本、asset 引用、proposal 等结构化内容 |
| `status` | streaming/completed/failed |
| `provider_item_id` | 仅诊断，可空 |
| `created_at/completed_at` | 时间 |

不持久化隐藏 chain-of-thought。

### `agent_runs`

| 字段 | 说明 |
|---|---|
| `id` | run ID |
| `owner_id/thread_id/conversation_id` | 隔离与关联 |
| `status` | run state |
| `model/provider/transport` | 实际调用信息 |
| `reasoning_effort` | 实际值 |
| `prompt_version/toolset_version` | 可复现版本 |
| `input_snapshot_json` | 已净化的 draft/asset 引用快照 |
| `usage_json` | input/output token、image、请求次数 |
| `provider_response_id` | 诊断字段 |
| `error_code/error_message` | 稳定错误 |
| `idempotency_key/request_hash` | 重复保护 |
| `created_at/started_at/finished_at` | 时间 |

唯一约束：owner + idempotency key。

### `agent_tool_calls`

| 字段 | 说明 |
|---|---|
| `id` | 本地 tool call ID |
| `provider_call_id` | provider ID，可空 |
| `owner_id/run_id` | 隔离 |
| `tool_name/tool_version/risk` | 工具身份 |
| `arguments_json/arguments_hash` | 已校验参数 |
| `status` | proposed/waiting_approval/running/succeeded/failed/rejected |
| `result_json` | 允许返回模型的净化结果 |
| `resource_type/resource_id` | 创建的 asset/job |
| `error_code/error_message` | 错误 |
| `created_at/started_at/finished_at` | 时间 |

唯一约束：run + provider call ID 或 run + local call ID。

### `agent_approvals`

| 字段 | 说明 |
|---|---|
| `id` | approval ID |
| `owner_id/run_id/tool_call_id` | 绑定 |
| `arguments_hash` | 防参数替换 |
| `status` | pending/approved/rejected/consumed/expired |
| `expires_at/decided_at/consumed_at` | 时间 |
| `decision_metadata_json` | 客户端版本等非敏感信息 |

### `agent_events`

| 字段 | 说明 |
|---|---|
| `id` | BIGSERIAL，全局 cursor |
| `owner_id/run_id/thread_id` | 隔离和索引 |
| `event_type` | 稳定名称 |
| `payload_json` | 浏览器可见的净化 payload |
| `created_at` | 时间 |

索引：`(owner_id, run_id, id)`。

### Asset provenance

给 Asset 增加：

- `source_type`：upload/job/agent-image/template；
- `source_agent_run_id`；
- `metadata_json`：provider、model、prompt hash、dimensions、request ID；

不向公共 API 输出 provider secret、storage path 或未净化原始 response。

## 3. 状态机

### Run

```text
queued
  → streaming
  → waiting_approval
  → executing_tool
  → streaming
  → completed

任一非终态 → cancelling → cancelled
任一非终态 → failed
waiting_approval → expired
Gateway restart 中断 → recovering → streaming | waiting_approval | failed
```

规则：

- `completed/failed/cancelled/expired` 为终态；
- run 不能从终态恢复；
- waiting approval 不保持 provider socket；批准后开始新 Responses turn；
- recovering 不盲目重放 costly tool。

### Tool call

```text
proposed
  → waiting_approval → approved → running → succeeded | failed
  → rejected
  → expired
read tool: proposed → running → succeeded | failed
```

### Approval

```text
pending → approved → consumed
pending → rejected | expired
```

## 4. API 草案

### Thread 与历史

```text
GET  /v1/conversations/{conversation_id}/agent/thread
GET  /v1/agent/threads/{thread_id}/messages?after=<sequence>&limit=50
```

Thread 可在首次 run 时惰性创建，避免额外创建步骤。

### Run

```text
POST /v1/agent/runs
GET  /v1/agent/runs/{run_id}
GET  /v1/agent/runs/{run_id}/events
POST /v1/agent/runs/{run_id}/cancel
```

创建请求：

```json
{
  "conversationId": "conversation-*",
  "message": "把这个想法整理成一个稳定的 5 秒镜头",
  "draftSnapshot": {},
  "assetIds": ["asset-*"],
  "mode": "assist"
}
```

规则：

- `draftSnapshot` 只接受共享 GenerationDraft 字段；
- asset ID 数量和大小受限；
- Conversation/Asset 必须属于 owner；
- 必须支持 `Idempotency-Key`；
- 返回 202 + run snapshot。

### Approval

```text
POST /v1/agent/tool-calls/{tool_call_id}/approve
POST /v1/agent/tool-calls/{tool_call_id}/reject
```

请求体不允许覆盖 tool arguments。approve 可包含用户可见备注，但不改变参数。

### Capability

```text
GET /v1/agent/capabilities
```

返回：

- text assistant 是否可用；
- image input/generation 是否可用；
- 可用工具和哪些需要审批；
- per-run 限制；
- provider 不可用时的稳定 reason code。

不返回 base URL、API key 或内部模型凭据。

## 5. SSE 事件

建议事件：

```text
agent.run.queued
agent.run.started
agent.message.delta
agent.message.completed
agent.tool.proposed
agent.approval.required
agent.tool.started
agent.tool.completed
agent.tool.failed
agent.asset.created
agent.draft.proposed
agent.job.created
agent.run.waiting_approval
agent.run.completed
agent.run.failed
agent.run.cancelled
heartbeat
```

每个 event：

```json
{
  "runId": "agent-run-*",
  "threadId": "agent-thread-*",
  "sequence": 12,
  "data": {}
}
```

注意：SSE `id:` 使用 `agent_events.id`，payload sequence 用于 UI 排序；二者不要混为一谈。

## 6. Durable SSE 规则

- 事件先提交 PostgreSQL，再广播；
- SSE 连接先读取 `id > Last-Event-ID`，再等待新事件；
- 每 15 秒 heartbeat；
- 终态事件发送后允许关闭；
- 断线重连先 GET run snapshot，再携带 last event ID；
- 不使用 `SessionEventService` 的进程内 list 作为 Agent canonical event；
- 多 Gateway 实例时可用 PostgreSQL polling/NOTIFY 或 Redis wake-up，但历史仍来自 PostgreSQL；
- 前端收到重复 event ID 必须幂等忽略。

## 7. BFF 显式路由

在 `apps/bff/proxy.py` 逐条增加：

- capabilities GET；
- run POST/GET/cancel；
- run events SSE；
- thread/messages GET；
- approve/reject POST。

要求：

- 不添加 `/v1/{path:path}` 通用代理；
- Agent POST 继续执行 Origin CSRF；
- JSON body 使用独立较小上限；
- `Last-Event-ID`、`Idempotency-Key` 继续 allowlist；
- SSE 设置 no-cache/no-buffering；
- owner 和服务断言流程与现有 API 一致。

## 8. Repository 与恢复

新增 `AgentRepository` 和 SQL/InMemory 两套实现，测试结构沿用 StudioRepository。

Gateway lifespan：

1. 扫描非终态 run；
2. `waiting_approval` 保持等待或标记过期；
3. `streaming` 变为 recovering，检查是否存在未完成 tool call；
4. read tool 可安全恢复；
5. costly tool 状态 unknown 时先对账 resource ID，不自动重放；
6. 无法安全恢复时标记 `AGENT_RECOVERY_REQUIRED`，保留已创建资源；
7. 不阻塞现有 JobService 启动。

## 9. API 错误和状态码

- 400：无效 mode/输入组合；
- 401：入口身份失效；
- 404：Conversation/Asset/Run/ToolCall 不存在或非当前 owner；
- 409：run 状态冲突、审批已消费、idempotency key 参数不一致；
- 413：上下文或图片过大；
- 422：schema、图片、tool 参数无效；
- 429：owner 配额或 provider 限流；
- 503：Agent 未配置/provider/circuit breaker 不可用。

## 10. OpenAPI 与测试

- Agent contract 放入 `packages/python/common`；
- Gateway OpenAPI 导出后更新前端 generated DTO；
- `pnpm check:api` 必须覆盖 Agent schema；
- repository 测试覆盖 owner 隔离和状态转移；
- PostgreSQL integration 覆盖 run/event restart；
- BFF 测试覆盖每条显式路由和伪造 owner；
- SSE 测试覆盖 replay、heartbeat、重复 cursor、终态关闭；
- migration upgrade/downgrade 在临时数据库验证。

## 11. 完成门

- Conversation、Run、Message、ToolCall、Approval、Event 均按 owner 查询；
- 跨 owner 全部为 404；
- Gateway restart 后历史和审批不丢失；
- EventSource 断线可从 cursor 恢复；
- 重复 run create/approve 不重复产生副作用；
- provider response storage 关闭时仍能从本地数据库完成多轮对话；
- Agent migration 不破坏现有 Conversation、Asset、Job 数据。
