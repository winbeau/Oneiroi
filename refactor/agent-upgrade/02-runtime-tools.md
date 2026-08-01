# 模块 2：AgentRuntime、工具与审批

## 1. 目标

构建一个有状态、受限、可取消和可恢复的 Agent 执行循环。模型负责提出计划和工具调用，Oneiroi 服务端负责授权、校验和真正执行。

## 2. 推荐代码布局

```text
services/gateway/src/oneiroi_gateway/agent/
  runtime.py
  context.py
  prompts.py
  provider.py
  openai_responses.py
  registry.py
  policy.py
  approvals.py
  events.py
  errors.py
  tools/
    conversation.py
    assets.py
    draft.py
    image.py
    jobs.py
```

职责：

- `AgentRuntime`：run loop、状态转移、provider 交互、取消与恢复；
- `ContextBuilder`：按 owner/thread 组装最小上下文；
- `ToolRegistry`：工具名、schema、风险、handler 和预算；
- `ToolPolicy`：决定自动执行、等待审批或拒绝；
- `ApprovalService`：一次性审批 token、参数哈希和过期；
- `AgentEventService`：durable event + SSE；
- tool handler：调用现有 repository/service，绝不信任模型传入 owner/path。

## 3. Run loop

推荐循环：

```text
create run
  → persist user message
  → build local context
  → call Responses provider with registered tools
  → stream text/tool events
  → no tool: validate final output → completed
  → read tool: validate → execute → persist result → continue model
  → approval tool: persist call → waiting_approval → stop current turn
  → approve: validate token/args → execute once → continue model
  → reject: persist rejection → continue or completed
```

边界：

- 每个 run 最多 8 个模型 turn；
- 最多 12 个 tool call；
- 最多 3 个需要审批的调用；
- 最大运行 300 秒，图片生成可使用单独上限；
- 单 owner 默认只允许 1 个 active run；
- 预算耗尽返回明确错误，不继续自治循环。

数值应配置化，但生产不能设为无限。

## 4. 工具风险等级

```python
class ToolRisk(StrEnum):
    READ = "read"
    PROPOSAL = "proposal"
    WRITE = "write"
    COSTLY = "costly"
    DESTRUCTIVE = "destructive"
```

策略：

- `READ`：owner 校验后自动执行；
- `PROPOSAL`：只生成候选，不修改服务端资源；
- `WRITE`：默认审批；
- `COSTLY`：每次审批并显示预算/参数；
- `DESTRUCTIVE`：每次审批，首版只开放 cancel，不开放 delete。

## 5. 首版工具清单

### 5.1 自动执行的只读工具

#### `get_creation_context`

输入：`conversationId`。

输出：

- Conversation 标题；
- 当前 draft snapshot；
- 已选首尾帧 asset ID 和安全元数据；
- 最近相关 Job 的有限 snapshot。

owner 来自 server context，不是工具参数。

#### `list_assets`

输入：类型、分页、可选关键词。

输出限制：

- 最多 20 项；
- 只返回 ID、标题、类型、尺寸、媒体类型、创建时间；
- 不返回 `storage_path`、内部 host 或完整 response JSON。

#### `get_asset_metadata`

输入：`assetId`。

先执行 owner 校验；不存在或越权统一为 not found。

#### `inspect_image_asset`

输入：`assetId` 和分析目标。

Runtime 读取受控文件并作为多模态 input 发送给 provider；模型看不到磁盘路径。

#### `get_job_snapshot`

输入：`jobId`。

返回真实 JobResponse 的允许字段，用于解释失败或生成进度。

### 5.2 Proposal 工具

#### `propose_draft_patch`

模型返回结构化 draft patch：

- prompt；
- negative prompt；
- ratio；
- resolution；
- duration；
- seed；
- first/last strength；
- first/last asset proposal。

该工具不修改 Zustand 或数据库。UI 必须展示 diff，由用户采用。

#### `propose_storyboard`

首版只返回文字镜头列表，不建立复杂 storyboard 数据库。它可作为图片生成和视频生成前的解释层。

### 5.3 需要审批的工具

#### `generate_reference_image` — COSTLY

参数：

- prompt；
- optional negative prompt；
- ratio/size；
- count，首版 1–2；
- optional reference asset IDs；
- purpose：first-frame、last-frame、style-reference。

审批后调用 image provider，结果进入 AssetService。

#### `create_video_job` — COSTLY

参数只能是现有 `JobCreate` contract 的受限子集。执行时：

- conversation、compute session、asset 均重新按 owner 校验；
- 复用 JobService 和 capability gating；
- 生成稳定 idempotency key；
- 不允许模型指定 output path、GPU UUID 或内部 profile ID。

#### `cancel_video_job` — DESTRUCTIVE

只取消 owner 自己的非终态任务。UI 显示 job 标题/ID 和当前阶段。

#### `retry_video_job` — COSTLY

复用 JobService retry；必须展示原失败原因和重试将再次占用算力。

### 5.4 首版禁止工具

- 删除 asset/conversation/job；
- shell、Python、SQL；
- 文件系统读取/写入；
- 任意 HTTP、Web 搜索和 URL fetch；
- gpu-server lease 或内部 endpoint；
- 修改 owner、Access policy、系统配置；
- 自动无限重试。

未来新增工具必须经过独立 threat model 和风险分级。

## 6. ToolRegistry contract

每个工具注册：

```text
name
version
description
input_schema
output_schema
risk
max_calls_per_run
timeout_seconds
idempotency_policy
handler
```

执行前检查：

1. 工具名在 registry；
2. 当前 Agent profile 允许；
3. arguments 严格 schema validate；
4. run、owner、conversation 状态有效；
5. 未超出 per-run/per-owner budget；
6. approval 状态与参数哈希匹配；
7. idempotency 尚未消费；
8. handler 内再次 owner 校验。

模型描述文字不是授权依据。

## 7. 审批设计

审批记录绑定：

- owner ID；
- run ID；
- tool call ID；
- tool name/version；
- canonical arguments SHA-256；
- 预计风险/成本；
- expires at；
- approved/rejected/consumed 状态。

审批 API 不接收新 arguments。用户只能批准或拒绝原调用；若参数变化必须创建新 tool call。

一次性规则：

- approval 最长 10 分钟；
- 只能消费一次；
- consumed 后重复 approve 返回当前 snapshot，不重复执行；
- owner 不匹配返回 404；
- run 已取消/过期则审批失效。

## 8. 幂等与重复执行保护

### Run 创建

客户端发送 `Idempotency-Key`。服务端绑定 owner + conversation + request hash。

### Tool call

内部 key：

```text
agent:{owner_hash}:{run_id}:{tool_call_id}:{arguments_hash}
```

- read 工具可安全重放；
- create image/job 先持久化 call，再执行；
- provider stream 重连不能产生第二个同 call ID 的执行；
- Gateway restart 后先查询 call 状态，再决定恢复、对账或失败；
- 不在未知结果时自动重复 costly 操作。

## 9. ContextBuilder

上下文按以下顺序构建：

1. 版本化 server instructions；
2. 当前 Agent profile 与工具规则；
3. Conversation 本地 summary；
4. 最近 N 条用户/assistant 消息；
5. 当前 draft snapshot；
6. 用户显式选择的 asset metadata/image input；
7. 最近必要的 tool result。

限制：

- 不自动把整个素材库和所有 Job 填入 prompt；
- tool result 做字段 allowlist 和长度截断；
- 大 thread 通过本地 summary 压缩；
- summary 本身带版本和来源 message cursor；
- 用户可以开启新 thread，避免无限上下文成本。

## 10. Prompt injection 防护

- system instructions 与用户/图片/OCR 内容分离；
- 明确图片、asset title、job error 和 tool result 都是不可信数据；
- 用户文本无法注册、重命名或改变工具风险；
- 工具 handler 不接受模型提供的 owner/header/path/base URL；
- 任何“忽略规则”“直接执行”等内容不影响 policy engine；
- 输出给下一个模型 turn 的 tool result 使用结构化 JSON，不拼接内部异常栈。

## 11. 取消与故障

- 用户可取消 active/streaming/waiting approval run；
- provider 请求取消后关闭 transport；
- running tool 尝试协作取消，但已提交的 image/job 必须对账；
- cancel 不等同于回滚已完成外部副作用；
- run snapshot 必须列出已完成资产/Job；
- Gateway 关闭时等待有界 grace，然后把未完成 run 标记为 interrupted/recovering。

## 12. 完成门

- 未注册工具永不执行；
- 所有工具在 handler 内进行 owner 校验；
- draft proposal 不自动改写用户内容；
- costly/destructive 工具无审批无法执行；
- 重复 approve、SSE 重连和 Gateway restart 不重复创建图片/Job；
- 达到 turn/tool/time budget 时可预测终止；
- 模型输出 malformed JSON 时记录失败且不触发副作用；
- 禁止工具通过自动化测试验证；
- run cancel 和 provider timeout 不泄漏后台 task。
