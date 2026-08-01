# 阶段 4：产品体验收口

## 目标

在 Fast 执行状态和错误契约稳定后，把当前产品壳收口为可邀请用户使用的创作 beta；优先真实状态、恢复和可解释性，不堆叠大功能。

## 当前已有

- 首页/灵感、创建页、会话侧栏、素材库和任务历史。
- 图片上传、首尾帧参数、Fast/HQ capability gating。
- Job timeline、取消、重试、结果预览、下载和设置复用。
- TanStack Query 管服务端状态，Zustand 管草稿/UI。
- reduced motion 和 warm-neutral 视觉 token。
- 生产 API 失败时不模拟成功；Demo 需要显式 `VITE_DEMO_MODE=true`。

## 主要缺口

### Agent

当前 `buildSuggestion()` 是本地固定模板，不是实际 Agent。界面“灵感搜索 · 创意设计”容易高估能力。

短期选择二选一：

1. 降级文案为“镜头提示词整理器”，保持本地确定性；或
2. 接入服务端参数编排 API，具备 loading/error/retry/audit，不直接在浏览器调用模型。

第一轮不需要多工具自治 Agent。

### 灵感与收藏

- 灵感模板主要是静态前端数据。
- 搜索是本地过滤。
- 缺用户收藏持久化、团队模板管理和真实历史案例入库。

先增加服务端收藏/模板模型，再考虑内容运营系统。

### SSE 恢复

- 当前 EventSource 出错后关闭连接并 invalidate query。
- 缺显式退避、cursor 和 `Last-Event-ID` 恢复。
- compute session event 仍是进程内内存历史。

应统一为 snapshot + durable cursor + reconnect。

### 用户体验

需要补齐：

- 新用户首次进入引导和可直接运行的模板。
- 无 Runner、排队、低水位、VPN 断开等真实错误文案。
- job 详情、attempt、耗时和失败原因面板。
- cancel requested 与 cancelled 的视觉区分。
- 长任务刷新后的恢复提示。
- 上传失败、格式错误和越权的明确状态。

## 工作包

### A. 状态与错误设计

- 建立稳定 error code → 用户文案映射。
- 所有不可用状态显示原因和下一步。
- 不用 timer 或本地 mock 推进生产任务状态。
- 提供 retryable、contact-admin 和 wait 三类操作建议。

### B. SSE/刷新恢复

- Job SSE 保存 last event ID。
- 断线指数退避重连。
- 重连前 GET snapshot 对账。
- 终态后关闭连接并刷新 asset。
- 多 tab 避免重复创建任务，仅共享只读状态。

### C. Agent 真实性

建议先实施“服务端提示词增强器”：

- 输入原始 idea 和当前 draft。
- 返回结构化 prompt、negative prompt、镜头、参数建议和理由。
- 用户确认后才写入 draft。
- 调用失败不改写原文。
- 记录版本、耗时和错误，不保存不必要的敏感输入。

### D. 素材与历史

- 区分用户上传、生成结果和模板。
- 收藏和标签服务端持久化。
- 搜索、筛选、排序与分页使用真实 API。
- 删除前显示引用关系；不能误删 job 仍依赖的 artifact。

### E. 浏览器 E2E

把 Playwright 纳入 CI 的稳定子集：

- 登录后创建 conversation。
- 上传图片。
- API 失败不假成功。
- SSE 更新、断线和刷新恢复。
- cancel/retry。
- MP4 Range/预览。
- 双用户越权由独立受控环境执行，不在公共 CI 暴露凭据。

## 完成门

- 用户能从登录到提交 Fast 任务再到历史/素材结果完成闭环。
- 所有失败都有真实状态和可操作文案。
- 页面刷新、SSE 断线不丢任务，也不重复提交。
- Agent 文案与真实能力一致。
- 新用户不阅读内部架构文档也能完成首次任务。
- 移动端和 reduced-motion 基础验收通过。

## 后续而非本阶段

- 文生视频、音频驱动、Retake、延展、画布编辑器。
- LoRA 用户管理、批量生产、协作评论、额度计费。
- 公共分享和开放注册。

## 预计时间

2–4 天；若接入真正的模型 Agent，则另加 2–5 天并单独评估安全、成本和延迟。
