# Oneiroi Studio LTX-2.3 动态 H100 后端与前端兼容方案

> 参考来源：官方应用仓库 `/tmp/LTX-Desktop`、Oneiroi 当前 Gateway/BFF/Runner 骨架，以及已经在 `h100-server` 跑通的 LTX-2.3 CLI 推理。
>
> 本文是目标架构和分阶段实施方案，不表示当前仓库已经具备真实热加载、动态 GPU 调度或持久任务执行能力。

## 1. 目标与结论

本方案要同时满足以下产品要求：

1. 默认申请最多 **4 张 H100**，但不写死 GPU 0–3；每次从当前允许且空闲的卡中动态选择。
2. 空闲卡少于 4 张时采用 best-effort：有几张就分配几张，并明确展示降级结果。
3. 只有 1 张卡时只加载 Fast，**后端和前端都禁用 HQ**。
4. 用户主动点击“热加载”后，Runner 才把模型权重加载到显存并进入可接任务状态。
5. 用户完成工作后主动点击“释放资源”；后端停止接新任务、等待或取消运行任务、退出模型子进程并确认显存释放。
6. 任务状态、GPU 状态、模型状态和资源会话状态必须分离，不能继续用浏览器定时器模拟。
7. 保持现有浏览器 → Pi BFF → H100 Gateway 的安全边界，浏览器永远不知道 H100 地址、服务器路径或内部凭据。

推荐的核心形态是：

```text
PostgreSQL 作为任务事实源
Redis Streams/租约作为实时调度通道
Gateway 作为资源与任务协调者
每张候选 GPU 一个轻量 Runner Supervisor
每次热加载启动一个绑定单卡的 Model Worker 子进程
```

这里选择“Supervisor 常驻、模型子进程按需启动/退出”，而不是只在一个 Python 进程里执行 `del pipeline; torch.cuda.empty_cache()`。退出子进程能销毁 CUDA context，更可靠地释放显存、规避碎片，并为加载失败或 OOM 提供清晰的故障隔离。

## 2. 已验证的 H100 基线

### 2.1 当前环境快照

在设计期间对 `h100-server` 做了只读核验：

- 主机：`zhengchen-ubuntu-8xh100-05`
- GPU：8 × NVIDIA H100 80GB HBM3
- 核验时 GPU 0、1、2、7 空闲，GPU 3–6 正被其他任务占用
- LTX-2 源码 commit：`9377758131b1ffde4b7f766804590a6617bf2ab9`
- 模型根目录：`/data/oneiroi/ltx-2.3`

已存在并验证的模型资产：

- `ltx-2.3-22b-distilled-1.1.safetensors`
- `ltx-2.3-22b-dev.safetensors`
- `ltx-2.3-22b-distilled-lora-384-1.1.safetensors`
- `ltx-2.3-spatial-upscaler-x2-1.1.safetensors`
- Gemma 3 12B 文本编码器

这次快照说明调度器不能假设“前 4 张卡就是可用卡”。默认 4 卡在当时应选择 0、1、2、7，而不是误占用 3–6。

### 2.2 已完成的冷启动 CLI 基准

同一首尾帧、5 秒、24 FPS、121 帧基准结果：

| 模式 | 分辨率 | CLI 总耗时 |
| --- | --- | ---: |
| Distilled draft | 768×512 | 37 秒 |
| Distilled 720p | 1280×704 | 42 秒 |
| Distilled 1080p | 1920×1088 | 62 秒 |
| Dev one-stage | 768×512 | 128 秒 |
| Dev production | 1280×704 | 101 秒 |
| Dev HQ | 1920×1088 | 176 秒 |

这些数字包含独立 CLI 进程的模型初始化成本，只能作为当前冷路径基线。热加载实现后必须重新拆分并记录：

- 子进程启动时间；
- 权重加载时间；
- warm-up 时间；
- Prompt 编码时间；
- 推理时间；
- 编码时间；
- 任务总时间；
- 峰值与稳定驻留显存。

### 2.3 当前 CLI 的正确定位

`scripts/run-ltx-2.3.sh` 和 `scripts/compare-ltx-2.3-quality.sh` 继续保留为：

- 人工 smoke test；
- 故障复现入口；
- 参数归一化和版本记录参考；
- Runner adapter 的回归基线。

生产任务不能继续“一任务启动一次 `python -m ltx_pipelines...`”，否则无法跨任务复用显存中的权重，也无法形成真正的热加载状态。

## 3. 从 LTX Desktop 借鉴什么

官方 Desktop 后端的主链路是：

```text
FastAPI route
  → AppHandler
    → domain handlers
      → typed AppState
      → service protocols / heavy side effects
```

Oneiroi 应借鉴以下设计。

### 3.1 单一组合根与明确服务边界

`/tmp/LTX-Desktop/backend/app_handler.py` 通过 `AppHandler` 统一持有：

- canonical runtime state；
- 共享锁；
- pipeline、generation、health 等 handler；
- GPU、模型、网络和任务执行 service。

Oneiroi Runner 的每个 Model Worker 也应有类似的组合根，例如 `WorkerApp`：

```text
WorkerApp
├─ WorkerState
├─ PipelineManager
├─ GenerationService
├─ GpuTelemetryService
├─ ArtifactService
└─ EventReporter
```

重型 PyTorch/LTX 实现必须通过 adapter/service 注入，测试使用 fake adapter，不在单元测试中真实加载 22B 模型。

### 3.2 显式资源槽和类型化状态机

Desktop 在 `state/app_state_types.py` 中将 GPU pipeline、CPU parked pipeline 和 generation 状态分开表示。Oneiroi 应保留这种“非法状态难以表示”的思路，但从单槽扩展为多 GPU slot，并把持久任务状态与进程内模型对象分开。

### 3.3 小锁区间

Desktop 的正确模式是：

1. 锁内检查和声明资源；
2. 锁外加载模型或执行推理；
3. 锁内重新校验并发布结果。

Oneiroi 的 Gateway 也不能在数据库事务或 Redis 分布式锁中执行几十秒的模型加载。租约只负责声明 GPU 所有权，真实加载在对应 Runner 上进行，通过事件更新状态。

### 3.4 模型驻留和确定性卸载

Desktop 会复用兼容 pipeline、交换 pipeline，并集中调用 GPU cleaner。Oneiroi 进一步增强为：

- 使用完整、不可变的 `PipelineSpec` 作为驻留缓存键；
- 一个 Model Worker 生命周期内只服务一个 profile；
- profile 切换通过退出旧子进程并启动新子进程完成；
- 释放按钮最终以进程退出为准，而不是只以 `empty_cache()` 返回为准。

### 3.5 后端发布能力，前端据此约束参数

Desktop 的 `/api/generate/models-specs` 让前端从后端获取可用模型、分辨率、FPS 和时长组合，并自动修正无效设置。Oneiroi 应增加统一 capabilities API，不能继续让前端写死 Fast/HQ、720p/1080p 或“有一张卡时仍能选 HQ”。

### 3.6 不直接照搬的部分

Desktop 面向单机单用户，因此有以下限制，不适合直接复制：

- 一个全局 GPU 槽；
- 一个全局 generation 状态；
- 长时间同步 `POST /api/generate`；
- 后台 daemon thread 无通用任务注册表；
- 取消主要是协作式检查；
- 模型缓存键没有覆盖所有 checkpoint/config 输入；
- renderer 本地恢复标记不是后端持久任务。

Oneiroi 必须使用异步 Job ID、持久任务记录、Runner 心跳、GPU 租约和可恢复事件流。

## 4. 目标部署架构

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

### 4.1 BFF 职责

Pi BFF 保持薄层：

- 从同源 cookie/session 得到可信用户身份；
- 显式转发 compute、job、asset、upload 和 SSE 路由；
- 限制上传大小和媒体类型；
- 转发下载并保留授权检查；
- 对私网不可达、Gateway 超时等错误做受控映射。

BFF 不再持有 `StudioStore` 任务状态，也不生成模拟完成结果。

### 4.2 Gateway 职责

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

### 4.3 Runner Supervisor 职责

每张候选 GPU 有一个轻量 Supervisor。它可以始终运行，但空闲时不创建 CUDA context：

- 使用 NVML 读取 GPU UUID、物理 index、显存、利用率、温度和 compute process；
- 定期向 Gateway/Redis 发送心跳；
- 接收 directed `load_profile`、`unload`、`run_job`、`cancel_job` 命令；
- 启动绑定单卡的 Model Worker 子进程；
- 监控 readiness、退出码、stderr 和显存；
- 子进程异常时将 slot 标记为 error，不把错误任务伪装成成功；
- unload 超时后依次执行 TERM 和 KILL；
- 子进程退出后确认显存回到基线阈值。

### 4.4 Model Worker 职责

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

## 5. GPU 与资源会话模型

### 5.1 GPU 可用性判定

一张 GPU 只有同时满足以下条件才进入 `eligible`：

1. 位于管理员配置的 allowlist；
2. 型号和显存满足 profile 最低要求；
3. 没有有效 Oneiroi lease；
4. 没有外部 compute process；
5. 显存占用低于空闲阈值，例如 2 GiB；
6. 最近心跳有效；
7. 没有 Xid/ECC/掉卡等硬件错误；
8. 不处于 draining、loading、busy 或 error 状态。

不要使用 P-state 作为空闲依据。设计期间空闲 H100 也显示 P0；应以进程、显存、利用率滑动窗口和租约为准。

推荐依赖 `nvidia-ml-py`/NVML，不在每个 API 请求中反复执行并解析 `nvidia-smi` 文本。

### 5.2 稳定标识

数据库和 Redis lease 使用 GPU UUID，不使用可重排的物理 index。API 可同时返回：

```json
{
  "id": "GPU-7f893bc3-...",
  "physicalIndex": 0,
  "name": "NVIDIA H100 80GB HBM3"
}
```

### 5.3 默认 1–4 卡 profile 分配

默认请求数为 4，实际分配数为：

```text
allocated = min(requested, eligible_count, configured_max=4)
```

默认 balanced profile 矩阵：

| 实际卡数 | Fast | HQ | 产品行为 |
| ---: | ---: | ---: | --- |
| 0 | 0 | 0 | 无法热加载 |
| 1 | 1 | 0 | HQ 强制禁用 |
| 2 | 1 | 1 | Fast/HQ 各一槽 |
| 3 | 2 | 1 | 优先 Fast 吞吐 |
| 4 | 2 | 2 | 默认完整配置 |

如果 HQ 权重缺失、HQ adapter 自检失败或 HQ slot 加载失败，不得把 HQ 任务静默降为 Fast。资源会话进入 `degraded`，前端显示实际可用 profile 及原因。

### 5.4 自动与手动选卡

热加载弹窗提供两种模式：

- `auto`：后端从 eligible 卡按评分自动选择；默认。
- `manual`：用户从后端返回的 eligible 列表中勾选 1–4 张卡。

自动评分建议考虑：

1. 无外部进程；
2. 显存使用最低；
3. 最近 GPU 利用率最低；
4. 温度较低；
5. 最近错误次数较少；
6. UUID 稳定排序作为最终 tie-breaker。

选择和 lease 创建必须在一次 Redis Lua/数据库事务语义内完成，避免两个请求同时选中同一卡。

## 6. 状态机

### 6.1 GPU slot 状态

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

### 6.2 Compute session 状态

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

### 6.3 Job 状态

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

## 7. 模型 profile 与热加载语义

### 7.1 Fast profile

建议 ID：`ltx23-distilled-fast-v1`

构造输入：

- Distilled 1.1 checkpoint；
- spatial upscaler 1.1；
- Gemma 3 12B；
- `fp8-cast`；
- `offload=none`；
- 固定 LTX-2 commit；
- 固定 attention backend；
- 可支持 draft、720p 和 1080p。

### 7.2 HQ profile

建议 ID：`ltx23-dev-hq-v1`

构造输入：

- Dev checkpoint；
- Distilled LoRA 384 1.1；
- spatial upscaler 1.1；
- Gemma 3 12B；
- `ti2vid_two_stages_hq` 对应 adapter；
- `fp8-cast`；
- `offload=none`；
- 初期只开放经过基准验证的 1080p 组合。

### 7.3 完整 PipelineSpec

不能只用 `fast/hq` 作为 pipeline 缓存键。建议：

```python
PipelineSpec(
    profile_id,
    ltx_git_commit,
    checkpoint_path,
    checkpoint_sha256,
    upsampler_path,
    upsampler_sha256,
    gemma_root,
    gemma_revision,
    lora_paths_and_scales,
    quantization,
    offload,
    dtype,
    attention_backend,
    compile_mode,
    runtime_policy_version,
)
```

任何字段变化都创建新 Model Worker，不复用旧 pipeline。

### 7.4 热加载完成条件

“热加载完成”不能等同于子进程存在。slot 只有满足以下条件才进入 `ready`：

1. checkpoint/hash 与 profile 完全匹配；
2. LTX pipeline 构造完成；
3. 核心权重已经按 profile policy 移入 GPU；
4. 必要 tokenizer/text encoder 初始化完成；
5. 可选 canonical shape warm-up 完成；
6. adapter 自检通过；
7. NVML/torch residency report 在合理范围；
8. Worker readiness probe 成功。

热加载事件应细分：

```text
reserving_gpu
starting_worker
loading_checkpoint
loading_text_encoder
moving_weights_to_gpu
warming_up
ready
```

首版不建议开启不可控的 `torch.compile`。如果后续启用，应作为独立 profile 版本，并明确 warm-up 对分辨率/帧数形状的影响。

### 7.5 释放流程

默认 release policy 为 `when_idle`：

1. session 进入 `draining`；
2. Gateway 停止向这些 slot 分配新任务；
3. 已排队未分配任务保留在队列或由用户取消；
4. 运行任务完成后，Supervisor 发送 unload；
5. Model Worker 清理临时文件、flush 事件后退出；
6. 超时后 Supervisor TERM，再超时 KILL；
7. NVML 验证显存回到基线；
8. 清除 Redis lease；
9. session 进入 `released`。

如果仍有运行任务，前端可提供显式 `cancel_running`，但必须二次确认，并先将任务置为 `cancel_requested`。

## 8. 调度与任务执行

### 8.1 不让 Runner 自由抢全局队列

为保证资源会话和 GPU 归属清晰，建议 Gateway 先选择 ready slot，再写入该 slot 的定向 Redis Stream：

```text
oneiroi:slot:{slot_id}:jobs
oneiroi:slot:{slot_id}:control
oneiroi:job:{job_id}:events
```

流程：

1. Gateway 创建持久 job；
2. 校验 compute session 和 profile capability；
3. 在数据库事务中创建 attempt 并绑定 slot；
4. XADD 到目标 slot stream；
5. Runner ACK 后状态变为 assigned；
6. Model Worker 逐阶段发事件；
7. Gateway 将事件落库并转发 SSE；
8. 成功时创建 asset 并保存真实 MP4 元数据。

### 8.2 slot 选择

同 profile 的 ready slot 按以下顺序选择：

1. 当前空闲；
2. 已加载完全相同 PipelineSpec；
3. 最近分配时间最早；
4. 最近失败率最低；
5. UUID 稳定排序。

热加载模式下不应为普通 job 临时交换 profile。没有 HQ ready slot 时，HQ job 保持 queued 或返回 `HQ_NOT_READY`，不驱逐 Fast profile。

### 8.3 取消

- queued：Gateway 原子标记 cancelled，禁止后续 assignment；
- assigned 但未开始：向目标 slot 发送 cancel；
- generating：设置 cancel flag，在 diffusion callback/step 边界停止；
- hard cancel：只作为超时后的显式策略，通过终止 Model Worker 实现；该 slot 随后必须重新热加载。

### 8.4 失败和重试

错误码至少区分：

- `NO_COMPUTE_SESSION`
- `COMPUTE_NOT_READY`
- `HQ_REQUIRES_AT_LEAST_2_GPUS`
- `HQ_NOT_READY`
- `GPU_BECAME_BUSY`
- `MODEL_LOAD_FAILED`
- `MODEL_PROFILE_MISMATCH`
- `CUDA_OOM`
- `INFERENCE_FAILED`
- `ENCODING_FAILED`
- `CANCELLED_BY_USER`
- `RUNNER_HEARTBEAT_LOST`
- `ARTIFACT_WRITE_FAILED`

重试创建新的 `job_attempt`，保留原任务和错误记录；不要覆盖前一次日志。

## 9. 数据模型

建议最小表：

### `compute_sessions`

- `id`
- `owner_id` / `workspace_id`
- `state`
- `requested_gpu_count`
- `allocated_gpu_count`
- `selection_mode`
- `profile_policy`
- `allow_partial`
- `created_at` / `ready_at` / `released_at`
- `error_code` / `error_message`

### `gpu_slots`

- `id`
- `runner_id`
- `host_id`
- `gpu_uuid`
- `physical_index`
- `state`
- `profile_id`
- `pipeline_spec_hash`
- `compute_session_id`
- `lease_expires_at`
- `vram_total_mib` / `vram_used_mib`
- `last_heartbeat_at`
- `last_error`

### `model_profiles`

- `id`
- `kind` (`fast`/`hq`)
- `version`
- `pipeline_spec_json`
- `enabled`
- `minimum_gpu_count_policy`
- `validated_at`

### `jobs`

- 用户原始请求；
- 服务端归一化参数；
- compute session/profile；
- 当前状态和进度；
- 当前 attempt；
- 结果 asset；
- 错误码；
- 时间戳。

### `job_attempts`

- job ID；
- slot/GPU UUID；
- Runner/Worker instance；
- cold/warm 命中；
- 各阶段耗时；
- 峰值显存；
- 日志和 manifest 路径；
- terminal reason。

### `job_events`

- 单调递增 event ID；
- job/session ID；
- event type；
- payload；
- created_at。

它用于 SSE 断线恢复和审计，不依赖浏览器 localStorage 猜测任务是否完成。

## 10. API 草案

所有浏览器 API 继续使用 `/v1`，由 BFF 显式代理。

### 10.1 GPU inventory

```http
GET /v1/compute/gpus
```

```json
{
  "requestedDefault": 4,
  "maximumSelectable": 4,
  "gpus": [
    {
      "id": "GPU-7f893bc3-...",
      "physicalIndex": 0,
      "name": "NVIDIA H100 80GB HBM3",
      "state": "empty",
      "eligible": true,
      "vramTotalMiB": 81559,
      "vramUsedMiB": 0,
      "utilizationPercent": 0,
      "unavailableReason": null
    }
  ]
}
```

### 10.2 后端能力与 profile

```http
GET /v1/compute/capabilities
```

返回 Fast/HQ 是否安装、是否允许、支持参数矩阵，以及当前会话下的可用性：

```json
{
  "profiles": [
    {
      "id": "ltx23-distilled-fast-v1",
      "tier": "fast",
      "available": true,
      "resolutions": ["720p", "1080p"],
      "durations": [5, 8, 10]
    },
    {
      "id": "ltx23-dev-hq-v1",
      "tier": "hq",
      "available": false,
      "unavailableReason": "HQ_REQUIRES_AT_LEAST_2_GPUS"
    }
  ]
}
```

### 10.3 热加载

```http
POST /v1/compute/sessions
Idempotency-Key: <uuid>
```

```json
{
  "requestedGpuCount": 4,
  "selectionMode": "auto",
  "gpuIds": [],
  "profilePolicy": "balanced",
  "allowPartial": true
}
```

返回 `202 Accepted`：

```json
{
  "id": "compute-...",
  "state": "loading",
  "requestedGpuCount": 4,
  "allocatedGpuCount": 3,
  "profilePlan": { "fast": 2, "hq": 1 },
  "slots": []
}
```

### 10.4 资源会话状态和事件

```http
GET /v1/compute/sessions/{session_id}
GET /v1/compute/sessions/{session_id}/events
```

SSE 事件：

```text
compute.session.updated
compute.slot.updated
compute.session.ready
compute.session.degraded
compute.session.released
```

### 10.5 释放

```http
POST /v1/compute/sessions/{session_id}/release
```

```json
{
  "policy": "when_idle"
}
```

如果使用 `cancel_running`，必须由前端二次确认并由后端鉴权。

### 10.6 Job API

保留现有稳定路径：

```http
POST /v1/jobs/i2v
GET /v1/jobs/{job_id}
GET /v1/jobs/{job_id}/events
POST /v1/jobs/{job_id}/cancel
GET /v1/jobs/{job_id}/file
```

扩展 create payload：

```json
{
  "conversationId": "...",
  "computeSessionId": "compute-...",
  "draft": {
    "queue": "fast"
  }
}
```

扩展 job response：

```json
{
  "stage": "generating",
  "progress": 54,
  "queuePosition": null,
  "profileId": "ltx23-distilled-fast-v1",
  "gpu": {
    "id": "GPU-...",
    "physicalIndex": 2
  },
  "attempt": 1,
  "warmStart": true,
  "phase": "diffusion",
  "currentStep": 5,
  "totalSteps": 8,
  "output": null,
  "error": null
}
```

## 11. 输入、输出与安全边界

### 11.1 上传

当前前端把图片转为 Data URL 并持久化到 Zustand/localStorage，这不适合真实后端。改为：

1. 浏览器 multipart 上传到 BFF；
2. BFF 流式转发到 Gateway；
3. Gateway 校验大小、MIME、解码结果和尺寸；
4. 返回不可猜测 asset ID；
5. Job 只引用 asset ID，不接受服务器路径或任意 URL。

### 11.2 任务目录

```text
/data/oneiroi/jobs/{job_id}/
├─ input/
├─ work/
├─ output/result.mp4
├─ logs/runner.log
├─ manifest.json
└─ metrics.json
```

目录由 Gateway/ArtifactService 创建。浏览器 payload 不能决定该路径。

### 11.3 下载

`GET /v1/jobs/{job_id}/file` 返回真实 MP4 或短时授权 URL，不再返回 JSON manifest。参数 manifest 可单独提供：

```http
GET /v1/jobs/{job_id}/manifest
```

### 11.4 身份

- 浏览器使用同源安全 cookie；
- BFF 从会话得到用户 ID；
- Gateway 只信任 BFF 签发的内部身份上下文；
- 原生 EventSource 不依赖自定义 `X-Oneiroi-User` header；
- 热加载/释放需要 `compute:manage` 权限；
- release 必须校验 owner/workspace 和活跃任务。

## 12. 前端修改方案

### 12.1 新增 ComputeControl

在生成页 header 或 Composer 上方增加紧凑资源控制条：

#### 空资源

```text
GPU 资源未加载                         [热加载]
```

#### 加载中

```text
正在热加载 2/4
GPU 0 Fast：moving weights 68%
GPU 1 Fast：ready
GPU 2 HQ：loading checkpoint
GPU 7 HQ：waiting
```

#### Ready

```text
4 张 H100 已就绪 · Fast 2 · HQ 2       [释放资源]
```

#### Degraded

```text
3/4 张 H100 已就绪 · Fast 2 · HQ 1
1 张卡被其他任务占用                   [查看详情] [释放资源]
```

建议新增目录：

```text
apps/web/src/features/compute/
├─ compute-control.tsx
├─ gpu-selector-popover.tsx
├─ compute-session-panel.tsx
├─ release-compute-dialog.tsx
├─ slot-status-row.tsx
├─ hooks.ts
└─ types.ts  # 最终由 OpenAPI 生成类型替代
```

### 12.2 热加载弹窗

字段：

- 选卡方式：自动 / 手动；
- 卡数：默认 4，最大值来自后端；
- 动态 GPU 列表：物理 index、型号、显存、占用、是否 eligible；
- profile 预览：例如 `2 Fast + 2 HQ`；
- `allowPartial`：默认开启；
- 加载后预计占用提示。

前端只能提交后端返回的 GPU ID；后端仍要重新校验，不能信任列表已过期前的空闲状态。

### 12.3 Fast/HQ 控件改造

Composer 不再用本地常量决定质量档：

- 从 `/v1/compute/capabilities` 读取 profile 和参数矩阵；
- 无 compute session 时禁用“生成”，提示先热加载；
- session loading 时展示加载状态；
- 只有 1 张卡时禁用 HQ，并显示“HQ 至少需要 2 张已分配 GPU”；
- HQ slot 没 ready 时禁用 HQ，而不是提交后静默改 Fast；
- 后端返回参数归一化结果后，UI 更新实际 resolution/frame count。

这沿用 Desktop 的“后端提供 model specs、前端只渲染有效组合”模式。

### 12.4 任务卡改造

现有 JobTimeline 增加真实阶段：

- loading model；
- Prompt 编码；
- diffusion step；
- stage-2/upscale；
- encoding。

任务卡展示：

- assigned GPU，例如 `GPU 2 · H100 80GB`；
- Fast/HQ profile；
- warm start / cold recovery；
- queue position；
- current step / total steps；
- cancel requested 与真正 cancelled 的区别；
- 后端错误码对应的可操作提示。

### 12.5 释放交互

点击“释放资源”后：

- 没有活跃任务：直接确认并展示逐卡 unloading；
- 有运行任务：默认只允许“任务完成后释放”；
- “取消任务并释放”放在危险操作区并二次确认；
- UI 等到 `compute.session.released` 才显示显存已经释放；
- 如果某卡显存未回落，显示具体 slot error，不能直接把界面变成 empty。

### 12.6 状态管理

- TanStack Query：GPU inventory、capabilities、compute session、jobs/assets 的服务端状态；
- Zustand：仅保存 Composer 草稿、会话选择和 UI 展开状态；
- SSE：实时更新 compute session 和 job；断线后用 `Last-Event-ID` 或 GET snapshot 恢复；
- 页面刷新：根据服务器 active compute session 和 jobs 重建 UI；
- 不再用浏览器 timer 推进真实任务。

### 12.7 取消生产环境模拟 fallback

当前前端在任务创建或 SSE 失败后会静默进入浏览器模拟成功流程。应改为：

- `VITE_DEMO_MODE=true` 时才启用显式 Demo 模式；
- production 构建中 API 失败就是失败；
- UI 明确展示 BFF/Gateway 不可用；
- 不创建假的成功资产。

### 12.8 OpenAPI 类型生成

参考 Desktop：

1. Gateway 用 Pydantic 定义 API DTO；
2. CI 导出 OpenAPI；
3. 生成 TypeScript types/client；
4. 前端禁止手写重复的 compute/job response 类型；
5. Runner 控制消息使用 `oneiroi_common` 中的 Pydantic contract，并做运行时校验。

## 13. 推荐代码布局

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

## 14. 分阶段实施

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

## 15. 验收标准

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

## 16. 需要先做的测量

在开始 P1 前还需要用真实 Python adapter 补充以下数据：

1. Fast profile 加载耗时和 ready 后稳定显存；
2. HQ profile 加载耗时和 ready 后稳定显存；
3. Fast/HQ 是否能让 Gemma、VAE、upsampler 和 transformer 同时保持目标驻留；
4. 720p/1080p 推理峰值显存；
5. 连续任务后的碎片增长；
6. 子进程退出到 NVML 显存回落所需时间；
7. 4 个 Worker 同时加载时的主机 RAM、磁盘读取和 page cache 压力；
8. 是否需要错峰加载，例如每 5–10 秒启动下一张卡。

默认建议串行或限并发热加载 4 张卡，避免四个 46GB checkpoint 同时读盘造成 IO 风暴；已经 ready 的卡可以先接任务，其余卡继续加载。

## 17. 最终决策摘要

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

## 18. 参考实现文件

LTX Desktop：

- `/tmp/LTX-Desktop/backend/architecture.md`
- `/tmp/LTX-Desktop/backend/app_handler.py`
- `/tmp/LTX-Desktop/backend/state/app_state_types.py`
- `/tmp/LTX-Desktop/backend/handlers/pipelines_handler.py`
- `/tmp/LTX-Desktop/backend/handlers/generation_handler.py`
- `/tmp/LTX-Desktop/backend/handlers/video_generation_handler.py`
- `/tmp/LTX-Desktop/backend/api_types.py`
- `/tmp/LTX-Desktop/backend/_routes/generation.py`
- `/tmp/LTX-Desktop/frontend/hooks/use-generation.ts`
- `/tmp/LTX-Desktop/frontend/lib/generation-progress-poll.ts`
- `/tmp/LTX-Desktop/frontend/hooks/use-video-generation-model-specs.ts`
- `/tmp/LTX-Desktop/frontend/lib/video-generation-model-specs.ts`

Oneiroi 当前基线：

- `scripts/run-ltx-2.3.sh`
- `scripts/compare-ltx-2.3-quality.sh`
- `apps/bff/src/oneiroi_bff/studio.py`
- `services/gateway/src/oneiroi_gateway/main.py`
- `workers/runner/src/oneiroi_runner/main.py`
- `workers/runner/src/oneiroi_runner/settings.py`
- `packages/python/common/src/oneiroi_common/jobs.py`
- `apps/web/src/store/studio-store.ts`
- `apps/web/src/features/create/job-card.tsx`
- `apps/web/src/features/create/job-timeline.tsx`
