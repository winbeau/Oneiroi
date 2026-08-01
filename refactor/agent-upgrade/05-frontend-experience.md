# 模块 5：Agent 前端体验

## 1. 目标

把当前单次本地提示词按钮升级为与 Conversation 绑定的 Agent 工作区，同时保持“建议必须由用户确认”的产品原则。

## 2. 组件布局

建议：

```text
apps/web/src/features/agent/
  agent-panel.tsx
  agent-thread.tsx
  agent-composer.tsx
  agent-message.tsx
  agent-status.tsx
  tool-call-card.tsx
  approval-card.tsx
  draft-diff-card.tsx
  generated-image-card.tsx
  hooks.ts
  types.ts
```

当前 `features/create/agent-panel.tsx` 逐步变成入口壳；数据和复杂交互迁入 `features/agent/`。

## 3. 主交互

### 输入区

- 自然语言输入；
- 当前 draft context chip；
- 用户显式选择的图片 asset chip；
- 模式：提示词优化、图片分析、生成参考图、任务规划；
- 发送后创建 run，而不是浏览器直接调用 provider。

### 流式内容

显示：

- assistant 可见回复；
- “分析素材”“整理镜头”“等待确认”“创建素材”等状态；
- tool card 和真实执行结果；
- provider/网络错误与重试入口。

不显示：

- 原始 chain-of-thought；
- system prompt；
- provider 原始事件；
- API key、base URL、storage path。

## 4. Draft proposal

`DraftDiffCard` 展示字段级 diff：

- prompt；
- negative prompt；
- ratio/resolution/duration；
- seed；
- strength；
- first/last frame。

用户操作：

- 全部采用；
- 单字段采用；
- 复制文本；
- 保留原 draft；
- 继续让 Agent 修改。

采用前不修改 Zustand。采用后仍由现有生成按钮/审批创建 Job。

## 5. 工具和审批卡

审批卡必须展示：

- 工具动作；
- 关键参数；
- 风险等级；
- 将创建的资源；
- 成本/配额提示；
- 过期时间；
- 批准与拒绝按钮。

按钮要求：

- pending 时防重复点击；
- 409 时 GET 最新 snapshot；
- approval consumed 后不可再次执行；
- 页面刷新后恢复 pending 状态；
- 不允许在前端编辑原 tool arguments 后直接批准。

## 6. 图片结果

生成图片卡：

- 真实 Asset preview；
- 尺寸、用途和创建状态；
- 设为首帧；
- 设为尾帧；
- 保存但不采用；
- 继续基于该图生成变体。

图片还没完成时不显示占位图为成功；失败时不写假 Asset ID。

## 7. Run/SSE hooks

建议 hooks：

- `useAgentCapabilities()`；
- `useAgentThread(conversationId)`；
- `useAgentMessages(threadId)`；
- `useCreateAgentRun()`；
- `useAgentRun(runId)`；
- `useAgentRunEvents(runId)`；
- `useApproveToolCall()`；
- `useRejectToolCall()`；
- `useCancelAgentRun()`。

SSE 策略：

1. 保存 last event ID；
2. 断线先 GET snapshot；
3. 指数退避重连；
4. 重复 event 幂等忽略；
5. terminal 后关闭；
6. reconnect 不重新 POST run。

TanStack Query 管服务端 thread/run/message；Zustand 只管 draft 和本地 UI。

## 8. 状态与文案

至少区分：

- Agent 未配置；
- provider 不可用；
- 正在连接；
- 正在生成文本；
- 正在执行只读工具；
- 等待审批；
- 图片生成中；
- 已取消；
- 配额达到；
- 输出格式异常；
- 网络中断，正在恢复；
- 已创建真实 Asset/Job。

Agent 不可用不能影响普通上传、手工编辑 prompt 和现有 Job 功能。

## 9. 与 Conversation 的关系

- Agent thread 跟随 active Conversation；
- 切换 Conversation 时切换 thread/history；
- 新建 Conversation 后可以直接发 Agent 消息；
- Conversation 标题可在首次成功响应后提出建议，但不自动修改；
- active run 在侧栏显示状态，避免切页后失踪。

## 10. 移动端和可访问性

- 手机端 AgentPanel 使用底部 sheet 或全宽折叠区；
- 消息和审批卡不依赖 hover；
- streaming 状态使用 `aria-live=polite`，避免每个 token 都播报；
- 关键按钮具备明确 accessible name；
- reduced-motion 下关闭逐 token/位移动画；
- 图片提供用户标题或生成描述作为 alt；
- 键盘可完成发送、采用、批准和拒绝。

## 11. E2E 场景

Playwright 稳定集：

- 提示词增强返回 proposal，未采用前 draft 不变；
- 部分采用后只修改选中字段；
- provider 失败不会生成假建议；
- SSE 断线后从 cursor 恢复，不重复消息；
- 图片生成 approval 前没有 provider 调用；
- approve 后出现真实 Asset 卡；
- 重复 approve 不生成第二张图；
- create video job approval 后出现真实 Job；
- cancel run 与 cancel video job 文案/状态分离；
- 跨 Conversation 不串消息；
- Agent capability 关闭时普通创建流程仍可用。

## 12. 完成门

- 当前本地固定模板不再冒充真实 Agent；
- 所有服务端状态都来自 API/SSE；
- 用户能看懂模型建议、工具动作和审批影响；
- 未确认 proposal 不修改 draft；
- 刷新、切页和短断网不重复 run/tool；
- raw reasoning、secret 和内部路径不出现在 DOM；
- mobile、键盘和 reduced-motion 基础验收通过。
