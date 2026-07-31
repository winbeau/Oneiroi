# Oneiroi Studio LTX-2.3 动态 H100 实施主计划

> 参考官方应用仓库 `/tmp/LTX-Desktop`，结合 Oneiroi 当前 Gateway/BFF/Runner 骨架及 `h100-server` 已跑通的 LTX-2.3 CLI 推理。
>
> 本文件只维护阶段简介、里程碑摘要和模块索引。架构、API、GPU 生命周期、前端和验收细节分别维护在子计划中，禁止再次把完整大工程计划堆回本文件。

## 1. 目标范围

本项目要实现一套由用户显式控制的 H100 推理资源池：

- 默认申请最多 4 张 H100；
- 不写死 GPU 0–3，从当前允许且真实空闲的卡中动态选择；
- 空闲卡少于请求数时采用 best-effort，有几张就分配几张；
- 1 张卡时只加载 Fast，后端和前端均禁用 HQ；
- 点击“热加载”后才将模型权重加载到显存并进入 ready；
- 用户完成后点击“释放资源”，通过退出模型子进程可靠释放 CUDA context 和显存；
- 任务、GPU slot、模型和 Compute session 使用独立状态机；
- 浏览器继续通过 Raspberry Pi BFF 访问 H100 Gateway，不直接接触私网地址、服务器路径和内部凭据；
- 生产任务使用真实 Gateway/Runner，不允许静默回退为浏览器模拟成功。

## 2. 总体架构摘要

```text
Browser
  → Raspberry Pi Web + BFF
  → H100 Gateway
      ├─ PostgreSQL：任务、尝试、事件、资产的事实源
      ├─ Redis：GPU 租约、定向任务流、控制流和心跳
      └─ Runner Supervisor × candidate GPU
            └─ 热加载时启动单卡 Model Worker
```

核心资源策略：

| 实际分配卡数 | Fast | HQ | 行为 |
| ---: | ---: | ---: | --- |
| 0 | 0 | 0 | 无法热加载 |
| 1 | 1 | 0 | HQ 强制禁用 |
| 2 | 1 | 1 | Fast/HQ 各一槽 |
| 3 | 2 | 1 | 优先 Fast 吞吐 |
| 4 | 2 | 2 | 默认完整配置 |

Model Worker 一个生命周期只驻留一个完整 `PipelineSpec`。profile 切换和资源释放通过退出旧子进程完成，不以单独调用 `torch.cuda.empty_cache()` 作为释放成功标准。

## 3. 阶段简介

### P0：契约与观测基线

建立 Compute session、GPU slot、Job、Runner control/event 的类型化契约；接入 NVML inventory 和 Runner heartbeat；测量 Fast/HQ 加载时间、驻留显存和推理阶段耗时。

退出条件：Gateway 能准确区分 Oneiroi 空闲、外部占用、离线和错误 GPU，并生成稳定 GPU UUID inventory。

### P1：单卡 Fast 热加载与释放

实现轻量 Supervisor、单卡 Model Worker 和 Fast LTX adapter。先完成一张动态空闲 GPU 上的显式热加载、连续任务复用和进程级释放。

退出条件：同一 Worker 连续执行 3 个任务不重复加载模型，释放后 CUDA 子进程消失且 NVML 显存回到基线。

### P2：1–4 卡动态资源池

加入 Redis GPU lease、自动/手动选卡、best-effort 分配、Compute session SSE 和心跳过期回收。

退出条件：请求 4 卡但只有 3 卡空闲时，系统只租约这 3 张，并得到 2 Fast + 1 HQ 的计划，不触碰外部占用卡。

### P3：HQ profile

实现独立 HQ adapter、完整 PipelineSpec、自检和 warm-up。HQ 失败不得静默降级为 Fast。

退出条件：2–4 卡 profile 矩阵正确；只有 1 卡时，HQ API 被后端硬拒绝，前端同步禁用。

### P4：持久任务与真实资产

以 PostgreSQL 保存 job、attempt、event 和 asset；以 Redis Streams 定向派发任务；实现上传、取消、重试、SSE 恢复和真实 MP4 下载。

退出条件：Gateway/浏览器刷新后任务可恢复，成功任务返回可播放 MP4，不再返回模拟 manifest 代替视频。

### P5：前端资源控制接入

增加 ComputeControl、GPU 选择器、逐卡热加载进度、释放确认和 capabilities 驱动的 Fast/HQ 参数约束。

退出条件：用户能完成“选卡 → 热加载 → 生成 → 观察任务 → 释放”的完整流程；生产 API 故障不会生成假的成功资产。

### P6：可靠性与容量验证

覆盖四卡并发、Runner 崩溃、OOM、外部进程占卡、租约超时、Redis/Gateway 短暂不可用和 unload timeout。

退出条件：所有异常均有明确状态、错误码、审计事件和恢复策略，不产生 GPU 双重分配或 orphan CUDA process。

### P7：不暴露公网的 API 验证

使用 ASGI client 和仅绑定 `127.0.0.1` 的临时服务完成 GET、POST、PUT、SSE 和下载测试；增加幂等 `PUT /v1/conversations/{conversation_id}`，并执行单卡 Compute session 私网热加载/释放 smoke test。

退出条件：测试端口未监听公网接口，没有新增 Cloudflare/DNS/路由入口，GET/POST/PUT 自动化和 loopback smoke test 均通过，临时服务已关闭。

## 4. 里程碑实现摘要

| 里程碑 | 主要交付 | 关键验收 |
| --- | --- | --- |
| M1 资源可见 | NVML inventory、GPU UUID、心跳、错误分类 | 可准确显示所有候选卡及占用原因 |
| M2 Fast 生命周期 | Supervisor、Fast Worker、热加载、释放 | 三次连续任务复用模型，释放显存 |
| M3 动态调度 | 1–4 卡租约、auto/manual、partial allocation | 不抢占外部任务，不依赖连续 index |
| M4 HQ 能力 | HQ Worker、ProfileSpec、能力矩阵 | 1 卡禁 HQ，2–4 卡按矩阵加载 |
| M5 真实任务 | PostgreSQL、Redis Streams、SSE、MP4 | 任务可恢复、取消、重试和下载 |
| M6 前端闭环 | ComputeControl、GPU 弹窗、真实 Timeline | 用户完成完整资源与生成生命周期 |
| M7 生产加固 | 故障注入、权限、审计、容量测试 | 无双租约、假成功或显存孤儿 |
| M8 私网 API 验证 | ASGI + loopback GET/POST/PUT、监听面检查 | 无公网监听、幂等 PUT、临时服务关闭 |

## 5. 模块子计划索引

| 子计划 | 内容 | 主要关联阶段 |
| --- | --- | --- |
| [01 参考设计与验证基线](./ltx-backend-plan/01-reference-and-baseline.md) | LTX Desktop 可借鉴模式、不可照搬部分、H100/模型/CLI 基线、参考文件 | P0 |
| [02 后端架构与状态机](./ltx-backend-plan/02-backend-architecture.md) | BFF、Gateway、Supervisor、Model Worker 职责，状态机和推荐代码布局 | P0–P2 |
| [03 GPU 资源生命周期](./ltx-backend-plan/03-gpu-resource-lifecycle.md) | 空闲判定、动态选卡、profile 矩阵、热加载、warm-up、释放和待测指标 | P1–P3 |
| [04 任务、API 与持久化](./ltx-backend-plan/04-job-api-and-persistence.md) | 定向调度、取消/重试、数据表、Compute/Job API、上传、资产和安全 | P2–P4 |
| [05 前端兼容方案](./ltx-backend-plan/05-frontend-compatibility.md) | ComputeControl、选卡弹窗、Fast/HQ 约束、任务卡、释放交互和状态管理 | P5 |
| [06 实施与验收](./ltx-backend-plan/06-implementation-and-validation.md) | 阶段详细任务、验收标准、可靠性与容量测试 | P0–P6 |
| [07 私网 API 验证](./ltx-backend-plan/07-private-api-validation.md) | 不暴露公网的 GET/POST/PUT、Compute session smoke test 和监听面检查 | P7 |

完整实现的新对话执行入口见 [`prompts/ltx-dynamic-h100-full-implementation.md`](./prompts/ltx-dynamic-h100-full-implementation.md)。

## 6. 稳定 API 边界

Conversation API 增加幂等 PUT：

```text
POST /v1/conversations
GET  /v1/conversations
GET  /v1/conversations/{conversation_id}
PUT  /v1/conversations/{conversation_id}
```

新增 Compute 资源 API：

```text
GET  /v1/compute/gpus
GET  /v1/compute/capabilities
POST /v1/compute/sessions
GET  /v1/compute/sessions/{session_id}
GET  /v1/compute/sessions/{session_id}/events
POST /v1/compute/sessions/{session_id}/release
```

保留并扩展现有任务 API：

```text
POST /v1/jobs/i2v
GET  /v1/jobs/{job_id}
GET  /v1/jobs/{job_id}/events
POST /v1/jobs/{job_id}/cancel
GET  /v1/jobs/{job_id}/file
GET  /v1/jobs/{job_id}/manifest
```

具体请求、响应、错误码和 SSE 事件见 [任务、API 与持久化子计划](./ltx-backend-plan/04-job-api-and-persistence.md)。

## 7. 跨模块强制决策

1. 显式热加载，不在应用启动时自动占用 H100。
2. 默认请求 4 张，但实际分配为 `min(requested, eligible, 4)`。
3. 使用 GPU UUID 做租约键，物理 index 只用于展示。
4. 1 张卡只允许 Fast；HQ 必须由后端 capabilities 和任务校验双重禁止。
5. Gateway 不导入 PyTorch；只有 Model Worker 持有 CUDA context。
6. 每张 ready slot 同一时刻最多运行一个任务。
7. PostgreSQL 是持久任务事实源，Redis 不是最终业务状态存储。
8. Gateway 先选择 slot，再写入该 slot 的定向 Redis Stream。
9. release 默认 `when_idle`；强制取消运行任务必须二次确认。
10. 释放成功必须同时满足子进程退出、租约清除和 NVML 显存回落。
11. BFF 保持薄层，不保存 GPU 或任务的 canonical state。
12. 前端由后端 capabilities 驱动，生产环境禁止模拟成功 fallback。
13. API smoke test 只使用 ASGI client、loopback 或批准的可信私网接口；禁止新增公网入口。

## 8. 文档维护规则

- 主文件只更新阶段、里程碑、跨模块决策和索引。
- 实现细节必须写入对应模块子计划。
- 新模块应新增独立文件并补充本页索引。
- 任一子计划接近 400–500 行时，继续按职责拆分，不扩展成新的超长文件。
- 跨模块冲突以本文件的阶段顺序和强制决策为准；技术细节以对应子计划为准。
