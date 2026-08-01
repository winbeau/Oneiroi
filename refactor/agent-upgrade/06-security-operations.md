# 模块 6：安全、成本与运维

## 1. 安全原则

Agent 增加的是“模型提出动作”的能力，不改变 Oneiroi 的信任边界：

- Cloudflare Access 决定入口用户；
- Pi BFF 映射稳定 owner 并签发服务断言；
- Gateway 验证 owner/断言；
- policy engine 决定工具是否可执行；
- 现有 service/repository 再次校验资源 owner；
- provider 输出永远不是授权证明。

## 2. Secret 管理

- 不提交 `gpt-tmp/auth.json`；
- API key 迁移到 H100 受限环境配置或 systemd/Supervisor credential 文件；
- 文件权限最小化，仅 Gateway runtime 用户可读；
- 不把 key 放入前端 env、Vite build、BFF response 或 OpenAPI；
- Settings 使用 `SecretStr`；
- HTTP client 日志禁止 Authorization header；
- health/capability 只返回 configured/available，不返回值；
- 当前明文 key 若曾离开受控本机或进入日志，应轮换。

建议把 `/gpt-tmp/auth.json` 加入 `.gitignore`，只保留不含凭据的参考配置或 `.example`。

## 3. Owner 隔离

所有 Agent 表和方法都接受 server-resolved owner：

- thread、message、run、tool call、approval、event 查询包含 owner；
- Conversation、Asset、Job 通过现有 owner-aware service/repository 访问；
- 越权和不存在都返回 404；
- 模型参数中的 owner/user/header 字段被 schema 拒绝；
- approval 不能由另一个 owner 消费；
- SSE 建连前验证 run owner，replay query 也包含 owner。

真实双用户验收必须覆盖文本、图片、approval、Asset 和 Job。

## 4. Prompt injection 与 tool abuse

防线：

1. system prompt 版本化且只由服务端提供；
2. 用户输入、素材标题、图片/OCR、Job error 都标记为不可信；
3. 工具只能来自 registry；
4. schema `additionalProperties=false`；
5. policy 基于工具元数据，不基于模型解释；
6. handler 忽略模型提供的 owner、路径和 host；
7. tool result 经过 allowlist 和长度限制；
8. 未知工具返回稳定拒绝，不尝试动态导入；
9. 首版没有 arbitrary web、shell、SQL 或文件工具。

## 5. SSRF、文件与媒体安全

- provider base URL 是静态配置；
- 图片 URL 只接受 provider adapter 产生并通过固定 allowlist；
- 禁止 loopback、RFC1918、link-local、metadata IP 和 DNS rebinding；
- 默认不跟随跨 host redirect；
- 下载有 connect/read/size 限制；
- 不把内部 storage URL 发给 provider；
- 图片完整 decode、像素限制、metadata strip；
- 文件写入 `.partial` 后原子 rename；
- 用户提供的文件名不成为磁盘路径。

## 6. 数据和隐私

虽然 provider 请求 `store=false`，仍需明确：

- 用户 prompt 和选择图片会发送给外部 provider；
- Oneiroi 本地会保存用户消息、assistant 结果、工具审计和 usage；
- 不保存隐藏 reasoning；
- 默认不把完整 provider 原始 response 长期落库；
- 日志记录长度、hash、ID 和状态，不记录完整 prompt/图片；
- 为 thread/message/event 定义保留策略和删除流程；
- 用户删除 Conversation 时未来需定义 Agent 历史和生成资产的级联/保留规则。

## 7. 配额和成本控制

配置维度：

- per-owner active runs；
- 每分钟 run 数；
- 每 run input/output token；
- 每 run turn/tool call；
- 每日图片数；
- 每日估算成本；
- 单次图片数量；
- 单 run 最大时长；
- provider 并发上限。

首版建议：

```text
active runs / owner = 1
turns / run = 8
tool calls / run = 12
approval calls / run = 3
images / approval = 1–2
images / run = 4
run timeout = 300s
```

配额命中使用 429 和稳定错误，不以长时间排队隐藏成本。

## 8. Circuit breaker 与降级

- 连续 auth 错误：立即 unhealthy，等待配置修复；
- 连续 5xx/timeout：短期开 circuit；
- 429：按 `Retry-After` 降低请求；
- Agent capability 返回 degraded reason；
- feature flag 关闭 Agent 时，普通 Conversation/Asset/Job 不受影响；
- 图片 capability 可独立关闭；
- costly job tools 可独立关闭，保留文本助手。

建议 flags：

```text
ONEIROI_GATEWAY_AGENT_ENABLED
ONEIROI_GATEWAY_AGENT_IMAGE_ENABLED
ONEIROI_GATEWAY_AGENT_JOB_TOOLS_ENABLED
ONEIROI_GATEWAY_AGENT_AUTO_READ_TOOLS_ENABLED
ONEIROI_GATEWAY_AGENT_WEBSOCKET_ENABLED
```

## 9. 审计日志

每个关键动作记录：

- owner hash；
- run/thread/tool call/approval/resource ID；
- provider/model/prompt/toolset version；
- status、latency、usage；
- arguments hash；
- approval outcome；
- error code；
- created Asset/Job ID。

不记录：

- API key；
- Authorization header；
- 完整图片 bytes/base64；
- storage path；
- 默认完整 prompt；
- hidden reasoning。

## 10. Metrics

建议：

- `agent_runs_total{status,model}`；
- `agent_run_duration_seconds`；
- `agent_provider_requests_total{status}`；
- `agent_provider_first_token_seconds`；
- `agent_tokens_total{direction}`；
- `agent_tool_calls_total{tool,status,risk}`；
- `agent_approvals_total{outcome,tool}`；
- `agent_image_generations_total{status}`；
- `agent_active_runs`；
- `agent_sse_connections`；
- `agent_recovery_total{outcome}`；
- `agent_budget_rejections_total{reason}`。

关联日志贯穿 BFF request ID、Agent run、tool call、Asset 和 Job。

## 11. 告警

- provider auth failure；
- 5xx/timeout 比例过高；
- tool execution unknown/重复冲突；
- costly tool 无审批执行计数必须为 0；
- owner isolation 404 之外的异常；
- image validation failure 突增；
- run recovery failure；
- PostgreSQL event backlog/SSE disconnect；
- 日成本或图片额度异常；
- 日志出现疑似 credential pattern。

## 12. 测试层级

### Unit

- provider event parser；
- strict schemas；
- policy matrix；
- approval token/hash；
- idempotency；
- context truncation；
- image validation；
- error mapping。

### Integration

- PostgreSQL thread/run/event restore；
- BFF owner/service assertion；
- SSE replay；
- Asset/Job tool；
- Gateway shutdown 不泄漏 task；
- fake provider timeout/429/5xx/断流。

### Security

- tool prompt injection；
- unknown tool；
- owner spoof；
- approval replay；
- arguments swap；
- SSRF/private redirect；
- oversized context/image；
- secret redaction。

### Manual canary

- 真实 GPT 文本；
- 多模态输入；
- 图片生成；
- approval；
- Asset/Job；
- provider 短断；
- Gateway restart；
- 两个真实用户隔离。

## 13. 发布和回滚

发布前：

- 默认 flags 全关；
- migration 先向前兼容；
- 部署 Gateway/BFF/Web 同一 release SHA；
- 先 capability probe，再单 owner canary；
- 不把 main 代码存在当作生产激活。

回滚：

- 先关闭 Agent/image/job flags；
- 不删除 Agent 数据表和已生成 Asset/Job；
- 回滚 Web/BFF/Gateway release；
- Access 始终保持启用；
- provider credential 可单独撤销；
- 已提交 Job 继续由正常 Job 系统管理。

## 14. 完成门

- secret 扫描、日志审查和权限检查通过；
- 没有任意网络/shell/SQL 工具；
- owner/approval/idempotency 安全测试通过；
- 配额、circuit breaker 和 feature flag 可验证；
- Agent 故障不影响现有产品核心 API；
- 生产有 usage、latency、error、cost 和 tool audit；
- 有明确 disable/rollback 操作且不需要数据库回退。
