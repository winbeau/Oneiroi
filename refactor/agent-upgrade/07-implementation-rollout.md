# 模块 7：实施阶段、验收与发布

## 1. 总体策略

按“无副作用文本 → durable runtime → 审批工具 → 图片 → 视频任务”递增风险。每阶段都可独立关闭和回滚，不一次上线完整自治 Agent。

生产 runtime 当前与 main 分离。所有新代码先本地和独立 canary 验证，再记录 Pi/H100 同一 release SHA 后部署。

## 2. 阶段 A：Secret 与 Provider Probe

**预计：0.5–1.5 天**

### 实施

- 将参考配置转为 Gateway settings；
- API key 迁移到受限环境配置；
- 忽略/移除仓库候选中的明文 auth 文件；
- 实现最小 capability probe CLI/受限测试；
- 验证 Responses 文本、SSE、tool、image input、image generation 和 usage；
- 保存不含凭据的 capability 记录。

### 验收

- `store=false` 实际发送；
- 文本 stream 可正常结束；
- function tool arguments contract 明确；
- 图片能力明确为 supported/unsupported；
- 日志、异常、进程参数不出现 key；
- 未配置时 Gateway 可正常启动且 Agent capability 为 disabled。

### 回滚

- 删除 Agent runtime env；
- 保持 `ONEIROI_GATEWAY_AGENT_ENABLED=false`；
- 不影响现有 API。

## 3. 阶段 B：只读 GPT 提示词助手

**预计：2–3 天**

### 实施

- Provider interface 和 SSE parser；
- `POST /v1/agent/runs` 的最小内存/短期实现，随后同阶段落 DB；
- 只允许当前 draft 和用户文本，不注册 write/costly 工具；
- 结构化 draft proposal；
- AgentPanel loading/error/diff/采用；
- BFF 显式 run/capability/events 路由；
- Mock provider 和前端 E2E。

### 验收

- 真实 GPT 返回 prompt proposal；
- 未采用前 draft 不变；
- provider 失败不生成本地假结果；
- 关闭 Agent 后现有本地创作流程仍可用；
- 跨 owner run 返回 404。

### 发布

- 只对单个内部 owner 或受限环境开启；
- 图片和 Job 工具保持关闭。

## 4. 阶段 C：Durable Thread/Run/Event

**预计：3–5 天**

### 实施

- Agent Pydantic contracts；
- Alembic `0002_agent_runtime`；
- SQL/InMemory AgentRepository；
- thread/message/run/event snapshot；
- durable SSE + `Last-Event-ID`；
- cancel、timeout、Gateway lifespan recovery；
- 本地 context summary；
- OpenAPI 和前端 generated DTO。

### 验收

- 页面刷新后消息/run 恢复；
- SSE 断线不丢、不重复；
- Gateway restart 后 completed/history 不丢；
- streaming 中断进入明确 recovering/failed；
- pytest 不残留 Agent background task；
- PostgreSQL integration 和 migration 测试通过。

### 回滚

- 关闭 Agent flag；
- 保留新增表；
- 不执行 destructive downgrade。

## 5. 阶段 D：受控工具与审批

**预计：2–4 天**

### 实施

第一批工具：

- `get_creation_context`；
- `list_assets`；
- `get_asset_metadata`；
- `inspect_image_asset`，若 image input 已验证；
- `get_job_snapshot`；
- `propose_draft_patch`。

基础设施：

- ToolRegistry；
- strict schema；
- risk policy；
- tool call/approval 表；
- approve/reject API；
- 参数哈希、TTL、幂等；
- tool/approval UI cards。

### 验收

- read 工具只看到当前 owner；
- unknown tool 和 extra args 被拒绝；
- approval 参数不能替换；
- 重复 approve 不重复执行；
- prompt injection 不能改变工具策略；
- run/tool/approval audit 完整。

### 发布

- 先启用自动 read 工具；
- write/costly 工具仍关闭。

## 6. 阶段 E：图片生成和素材化

**预计：2–4 天**

### 前置

- provider probe 确认图片生成 contract；
- Asset provenance migration/字段完成；
- 配额和审批可用。

### 实施

- `generate_reference_image` COSTLY 工具；
- 图片输出 adapter；
- base64/file ID/allowlisted URL 处理；
- Pillow decode、像素/size/hash、metadata strip；
- `.partial` + 原子写；
- ArtifactService generated image；
- 图片卡和设为首尾帧操作；
- usage/cost metrics。

### 验收

- 审批前 provider 不收到图片生成请求；
- 结果进入当前 owner Asset 列表；
- 另一 owner 读取 404；
- 结果可作为首帧/尾帧提交普通 Job；
- 畸形/超大/SSRF 输出拒绝；
- provider 中断不留下正式 partial Asset；
- 图片 capability 独立关闭可降级。

### 发布

- 单 owner、每次 1 张、并发 1；
- 观察成本和错误后再提高到 2 张。

## 7. 阶段 F：视频 Job 编排

**预计：2–3 天**

### 前置

- 现有 gpu-server/Fast 真实生成链可用；
- Job create/cancel/retry contract 稳定；
- costly tool 幂等和审批通过。

### 实施

- `create_video_job`；
- `cancel_video_job`；
- `retry_video_job`；
- 审批卡展示最终 draft、asset、compute/profile 和成本动作；
- 调用现有 JobService；
- Agent message 引用真实 Job ID；
- UI 联动现有 Job SSE/timeline。

### 验收

- 无审批不能创建 Job；
- 重复 approve 只创建一个 Job；
- compute unavailable 返回真实失败；
- Agent 不绕过 capability/owner/idempotency；
- cancel requested 和 cancelled 正确区分；
- 模型文本不能伪造 Job 成功。

### 回滚

- 关闭 `ONEIROI_GATEWAY_AGENT_JOB_TOOLS_ENABLED`；
- 文本/图片 Agent 可继续使用；
- 已创建 Job 由正常系统继续管理。

## 8. 阶段 G：Canary 与生产加固

**预计：2–4 天**

### 实施

- per-owner token/image/cost quota；
- circuit breaker；
- request/run/tool correlation；
- metrics、dashboard、告警；
- retention/cleanup；
- Playwright 稳定场景进 CI；
- provider contract test；
- 双真实 Authentik 用户验收；
- run/SSE/Gateway restart/provider 断网演练。

### 放量顺序

1. 内部管理员、文本 only；
2. 内部管理员、read tools；
3. 单 owner、图片 1 张；
4. 两个真实 owner；
5. Job tools 串行；
6. 小范围邀请用户；
7. 根据成本和错误提高额度。

### 最终验收

- 连续 20 个文本 run 无状态丢失；
- 连续 10 个图片 tool call 至少 9 个成功，失败无脏资产；
- 重复请求/审批不重复副作用；
- Gateway restart 后 pending approval 和历史恢复；
- provider 短断后状态明确且可重试；
- 双 owner thread/message/asset/job/SSE 全隔离；
- 关闭任一 feature flag 可立即降级；
- 成本、错误、工具和审批均可观测。

## 9. 每阶段质量门

每个实现阶段运行：

```text
uv run ruff check .
uv run pytest
pnpm check
pnpm check:api
pnpm --filter @oneiroi/web build
git diff --check
```

Agent 阶段额外要求：

- provider fixture/contract tests；
- PostgreSQL migration/integration；
- SSE replay；
- owner isolation；
- secret redaction；
- Playwright Agent 场景；
- 无 pending asyncio task。

远端 canary 记录：

- Pi/H100 release SHA；
- Agent flags；
- provider model/transport/capability；
- 测试 owner 范围；
- run/tool/Asset/Job ID；
- 验收结果；
- 回滚动作。

不记录 credential、Access cookie、完整 prompt 或图片 base64。

## 10. 预计工作量

| 工作包 | 预计 |
|---|---:|
| Provider/probe/config | 1–2 天 |
| Contracts/repository/migration | 2–3 天 |
| Runtime/SSE/recovery | 3–5 天 |
| Tool/approval/policy | 2–4 天 |
| 图片生成/资产化 | 2–4 天 |
| 前端 Agent 工作区 | 3–5 天，可与后端部分并行 |
| Job tools/集成 | 2–3 天 |
| 安全/CI/canary | 2–4 天 |

综合排期约 12–20 个工作日。最大的未知不是 React，而是自定义 provider 的图片、tool continuation、WebSocket 和 usage 兼容性，以及 gpu-server 真实 Fast 链是否已经可用。

## 11. 交付里程碑

### M1：真实 GPT 提示词增强

- 文本 stream；
- proposal diff；
- 无副作用；
- 单 owner canary。

### M2：可恢复 LLM Agent

- durable thread/run/event；
- read tools；
- approval framework；
- Gateway restart recovery。

### M3：图片创作 Agent

- image input；
- approved image generation；
- Asset provenance；
- 首尾帧采用。

### M4：生成任务 Agent

- approved Job create/cancel/retry；
- 真实 Job SSE；
- gpu-server Fast E2E。

### M5：邀请用户 Beta

- 双用户隔离；
- 配额/成本/告警；
- CI/E2E；
- feature flag 与回滚演练。

## 12. 下一步实施入口

正式编码从阶段 A 开始，不应直接改 AgentPanel 调真实接口。第一批 PR 应仅包含：

1. secret/config 与 capability model；
2. provider protocol 和 fake provider；
3. Responses SSE parser contract tests；
4. disabled-by-default capability endpoint；
5. 不含真实凭据的配置文档。
