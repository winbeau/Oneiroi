# 后端组件、状态机与代码布局

> 本文件是 [LTX-2.3 动态 H100 主计划](../ltx-desktop-inspired-backend-plan.md) 的模块子计划。跨模块范围、阶段顺序和里程碑以主计划为准。

## 目标部署架构

```text
Browser
  │ HTTPS / same-origin cookie
  ▼
Raspberry Pi
├─ Web static files
└─ FastAPI BFF
     │ explicit /v1 proxy only
     ▼
H100 private network
┌─────────────────────────────────────────────────────────────┐
│ Gateway                                                     │
│ ├─ Auth/context mapping                                     │
│ ├─ ComputeSessionService                                    │
│ ├─ GpuAllocator                                             │
│ ├─ JobService / Scheduler                                   │
│ ├─ SSE event fan-out                                        │
│ └─ Artifact authorization                                   │
│                                                             │
│ PostgreSQL                 Redis                             │
│ ├─ jobs                    ├─ GPU leases                    │
│ ├─ job_attempts            ├─ directed control streams     │
│ ├─ job_events              ├─ per-slot job streams          │
│ ├─ compute_sessions        └─ heartbeat/ephemeral state     │
│ ├─ gpu_slots                                                  │
│ └─ assets                                                     │
│                                                             │
│ Runner Supervisor × candidate GPU                           │
│ ├─ no Torch/LTX import while empty                          │
│ ├─ NVML telemetry + foreign-process detection               │
│ ├─ launches/stops Model Worker child                        │
│ └─ verifies CUDA memory is released                         │
│      └─ Model Worker                                        │
│         ├─ CUDA_VISIBLE_DEVICES=<GPU UUID>                   │
│         ├─ LTX Fast or HQ adapter                           │
│         ├─ one job at a time                                │
│         └─ progress/cancel/artifact events                   │
└─────────────────────────────────────────────────────────────┘
```

### BFF 职责

Pi BFF 保持薄层：

- 从同源 cookie/session 得到可信用户身份；
- 显式转发 compute、job、asset、upload 和 SSE 路由；
- 限制上传大小和媒体类型；
- 转发下载并保留授权检查；
- 对私网不可达、Gateway 超时等错误做受控映射。

BFF 不再持有 `StudioStore` 任务状态，也不生成模拟完成结果。

### Gateway 职责

Gateway 是资源和任务事实协调者：

- 枚举和聚合 Runner/GPU 状态；
- 原子创建 GPU 租约；
- 创建、加载、释放 compute session；
- 校验任务能力和参数；
- 持久化 job/job attempt/event；
- 将任务定向分配到 ready slot；
- 提供 SSE、取消、重试和授权结果下载；
- 在心跳过期后执行租约回收和任务恢复。

Gateway 不导入 PyTorch，也不直接持有 pipeline。

### Runner Supervisor 职责

每张候选 GPU 有一个轻量 Supervisor。它可以始终运行，但空闲时不创建 CUDA context：

- 使用 NVML 读取 GPU UUID、物理 index、显存、利用率、温度和 compute process；
- 定期向 Gateway/Redis 发送心跳；
- 接收 directed `load_profile`、`unload`、`run_job`、`cancel_job` 命令；
- 启动绑定单卡的 Model Worker 子进程；
- 监控 readiness、退出码、stderr 和显存；
- 子进程异常时将 slot 标记为 error，不把错误任务伪装成成功；
- unload 超时后依次执行 TERM 和 KILL；
- 子进程退出后确认显存回到基线阈值。

### Model Worker 职责

Model Worker 是唯一导入 Torch/LTX 的进程：

- 启动时只看到逻辑 `cuda:0`；
- 根据不可变 `PipelineSpec` 创建 Fast 或 HQ pipeline；
- 权重加载、warm-up 完成后发出 `ready`；
- 一个时刻只执行一个 job；
- 在 diffusion step/callback 安全点检查取消；
- 输出只写入服务端分配的 job 目录；
- 通过结构化事件报告阶段、step、耗时、显存和错误码。

物理 GPU 用 UUID 标识，例如设置：

```text
CUDA_VISIBLE_DEVICES=GPU-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
```

子进程内部只使用 `cuda:0`，禁止再次把物理 index 传给 LTX adapter，避免二次映射。

## 状态机

### GPU slot 状态

```text
offline
  ↓ heartbeat
empty
  ↓ lease acquired
reserved
  ↓ load command
loading
  ↓ model + warm-up ready
ready
  ↓ job assigned
busy
  ↓ job terminal
ready
  ↓ release requested
unloading
  ↓ child exited + VRAM verified
empty
```

附加状态：

- `draining`：不接新任务，等待当前任务结束；
- `error`：模型加载失败、子进程崩溃、OOM 或显存无法释放；
- `foreign_busy`：发现非 Oneiroi 进程，不可分配。

### Compute session 状态

```text
requested
  → allocating
  → loading
  → ready | degraded | failed
  → draining
  → releasing
  → released
```

Compute session 至少记录：

- owner/workspace；
- requested 和 allocated GPU 数；
- selection mode；
- GPU UUID 列表；
- profile plan；
- ready slot 数；
- 创建、ready、release 时间；
- release policy；
- 最后错误。

### Job 状态

在现有状态机上增加模型与取消的真实语义：

```text
draft
→ uploaded
→ queued
→ assigned
→ loading_model   # 仅允许恢复/替换 worker 时出现
→ preparing       # 图片预处理、Prompt 编码
→ generating
→ encoding
→ succeeded
```

取消分为：

```text
cancel_requested → cancelled
```

任一阶段可进入 `failed`。`cancel_requested` 表示后端已收到意图，但计算尚未到达安全停止点，不能立即显示“显存已释放”。

GPU slot 状态和 Job 状态不得复用同一个 enum。

## 推荐代码布局

```text
packages/python/common/src/oneiroi_common/
├─ compute.py
├─ generation.py
├─ events.py
├─ errors.py
└─ runner_protocol.py

services/gateway/src/oneiroi_gateway/
├─ routes/
│  ├─ compute.py
│  ├─ jobs.py
│  ├─ assets.py
│  └─ uploads.py
├─ services/
│  ├─ compute_sessions.py
│  ├─ gpu_allocator.py
│  ├─ job_scheduler.py
│  ├─ event_service.py
│  └─ artifact_service.py
├─ repositories/
├─ db/models/
└─ redis/

workers/runner/src/oneiroi_runner/
├─ supervisor.py
├─ worker_process.py
├─ state.py
├─ control_stream.py
├─ telemetry.py
├─ adapters/
│  ├─ base.py
│  ├─ ltx23_fast.py
│  └─ ltx23_hq.py
└─ services/
   ├─ gpu_cleanup.py
   ├─ artifact_writer.py
   └─ event_reporter.py

apps/bff/src/oneiroi_bff/
├─ routes/compute.py
├─ routes/jobs.py
├─ routes/uploads.py
└─ gateway_client.py

apps/web/src/features/compute/
└─ ...
```

---

[返回主计划](../ltx-desktop-inspired-backend-plan.md)
