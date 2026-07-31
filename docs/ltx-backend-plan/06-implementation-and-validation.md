# 阶段实施、验收与可靠性测试

> 本文件是 [LTX-2.3 动态 H100 主计划](../ltx-desktop-inspired-backend-plan.md) 的模块子计划。跨模块范围、阶段顺序和里程碑以主计划为准。

## 分阶段实施

### P0：契约和观测基线

- 定义 compute/slot/job/runner Pydantic 状态；
- 增加 NVML inventory 和 Runner heartbeat；
- 记录 Fast/HQ 冷加载、驻留显存和阶段耗时；
- 建立 OpenAPI → TypeScript 生成；
- 不执行真实调度。

验收：Gateway 能准确显示所有允许 GPU，并识别核验时类似 0、1、2、7 空闲、3–6 外部占用的场景。

### P1：单卡 Fast 热加载/释放

- 实现 Supervisor + Model Worker；
- 抽取 `ltx23_fast` Python adapter；
- `POST compute session` 只申请 1 卡；
- 热加载、3 次连续生成、释放；
- process exit 后验证显存回落。

验收：同一 Worker 连续 3 个任务不重复加载模型，结果目录隔离，无持续显存增长。

### P2：1–4 卡动态分配

- Redis GPU lease；
- auto/manual 选卡；
- best-effort 分配；
- balanced profile 矩阵；
- session SSE；
- 心跳过期回收。

验收：请求 4 卡但只有 3 卡空闲时，返回 3 卡且 profile 为 2 Fast + 1 HQ；不触碰外部占用卡。

### P3：HQ profile

- 抽取 `ltx23_hq` adapter；
- 完整 PipelineSpec；
- HQ readiness/warm-up；
- 只有 1 卡时 API 强制拒绝 HQ；
- HQ 失败不静默降级。

验收：2–4 卡 profile 矩阵正确，HQ 输出与现有 176 秒 CLI 基线可对比。

### P4：持久任务和真实资产

- PostgreSQL migrations；
- Redis directed streams；
- upload/asset/job attempt/event；
- SSE 重连；
- cancel_requested/cancelled；
- 真实 MP4 下载。

### P5：前端接入

- ComputeControl、GPU selector、热加载和释放；
- 后端 capabilities 驱动 Composer；
- JobTimeline 真实阶段；
- 生产关闭模拟 fallback；
- 刷新恢复 active session/jobs。

### P6：可靠性与容量测试

- 4 个并发 Fast/HQ job；
- Runner 崩溃；
- Redis/Gateway 短暂不可用；
- 外部进程抢占 GPU；
- OOM；
- unload timeout；
- 服务重启后的租约 reconcile；
- 24 小时 idle TTL 和显存回收策略。

## 验收标准

### 热加载

- 默认请求 4 卡；
- 动态选择实际空闲卡，不依赖连续 index；
- 少卡时正确 partial allocation；
- 1 卡时只有 Fast ready，HQ API 和 UI 均禁用；
- ready 前不允许提交到该 profile；
- 每张卡可看到加载阶段和错误。

### 任务

- 同一 ready slot 连续 3 个任务不重新加载权重；
- 4 卡并发时每张卡最多一个任务；
- job、attempt、event 和 asset 可在 Gateway 重启后恢复；
- 取消状态真实，不由前端自行推进；
- 输出 MP4 可播放并有 manifest/metrics。

### 释放

- release 后停止新分配；
- 默认等待运行任务结束；
- Model Worker 子进程全部退出；
- NVML 显存回到配置的 baseline；
- Redis lease 清理；
- 无 orphan CUDA process；
- 释放失败时 UI 显示具体 GPU，而不是伪装成功。

### 安全

- 浏览器不接受或提交服务器路径；
- GPU IDs 必须来自后端 inventory 且提交后再次校验；
- 热加载/释放有权限控制和审计；
- 模型、上传、结果和 token 不进入 Git；
- H100 正式服务使用专用非 root 用户。

## 最终决策摘要

- **显式热加载，不在应用启动时自动占用 H100。**
- **默认 4 卡、动态空闲卡、best-effort 少卡分配。**
- **1 卡只加载 Fast，HQ 在后端硬性禁用。**
- **4 卡默认 2 Fast + 2 HQ。**
- **每 GPU 一个轻量 Supervisor，每次热加载一个模型子进程。**
- **通过退出模型子进程实现可靠释放。**
- **PostgreSQL 是任务事实源，Redis 只做租约、调度和实时事件。**
- **Gateway 先分配 slot，再向 slot 定向派发任务。**
- **BFF 保持薄层，浏览器不接触 H100 和服务器路径。**
- **前端由后端 capabilities 驱动，生产环境禁止模拟成功 fallback。**

---

[返回主计划](../ltx-desktop-inspired-backend-plan.md)
