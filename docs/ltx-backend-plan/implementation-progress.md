# LTX 动态 H100 实施进度

> 只记录已经由代码、自动化测试或目标主机只读检查验证的事实。里程碑提交使用本文件所在提交或后续阶段补录的 Git hash 标识。

## 当前状态

| 阶段 | 里程碑 | 状态 | 对应提交 |
| --- | --- | --- | --- |
| P0 | M1 资源可见 | 已完成 | `e5af69e` |
| P1 | M2 Fast 生命周期 | 已完成 | `b3956fd`、`4e5299f`、`201c1bc`、`e13bc0d` |
| P2 | M3 动态调度 | 已完成 | `3304dba` |
| P3 | M4 HQ 能力 | 已完成 | `00dacc9`、`375fc95`、`fcae104` |
| P4 | M5 真实任务 | 未开始 | — |
| P5 | M6 前端闭环 | 未开始 | — |
| P6 | M7 生产加固 | 未开始 | — |
| P7 | M8 私网 API 验证 | 未开始 | — |

## M1：Compute 契约、GPU inventory 与 heartbeat

已验证实现：

- `oneiroi_common.compute` 定义独立的 GPU slot、Compute session、profile plan、完整 `PipelineSpec` 和 API DTO；
- Job 状态增加 `loading_model` 与非终态 `cancel_requested`，未与 GPU/Compute 状态复用；
- 分配上限固定为 4，balanced profile 纯函数覆盖 0–4 卡矩阵；
- GPU 稳定标识强制使用 `GPU-...` UUID，physical index 仅展示；
- Runner NVML telemetry 按 allowlist、外部 compute PID、显存阈值、硬件错误和 lease 语义分类，不使用 P-state；
- Runner heartbeat 使用独立 Redis Stream `oneiroi:runner:heartbeats` 契约；
- Gateway 提供 `GET /v1/compute/gpus`，默认不启用本机 NVML；启用时从 NVML 实时读取 inventory；
- Runner 的 `CUDA_VISIBLE_DEVICES` 绑定从物理 index 改为 GPU UUID，不再默认占用 GPU 0。

自动化检查：

- `uv run ruff check .`：通过；
- `uv run pytest`：18 项通过；
- `git diff --check`：通过。

H100 只读 inventory（2026-07-31）：

- 8 × NVIDIA H100 80GB HBM3，ECC 未修正错误计数均为 0；
- eligible 候选 physical index：0、1、2、7，显存使用均为 0 MiB；
- physical index 3–6 分别使用约 39989、50093、39621、50115 MiB，必须判定为不可分配；
- 候选 UUID（截断）：`GPU-7f893bc3…`、`GPU-5cae32f8…`、`GPU-6ff18a65…`、`GPU-2376be1e…`；
- 未启动 Model Worker，未创建 CUDA context，未修改任何外部进程。

未解决阻塞：无。

## M2：单卡 Fast Model Worker 生命周期

已验证实现：

- Supervisor 本身不导入 Torch/LTX，只在显式 `load()` 后启动绑定单 GPU UUID 的 Model Worker 子进程；
- Model Worker 完成 adapter load、组件初始化、自检/synchronize 后才发布 ready；
- `Ltx23FastAdapter` 直接构造官方 `DistilledPipeline` 并在同一子进程中跨任务复用；
- fake adapter 在本地生成隔离任务目录和真实 H.264 MP4，用于不占 GPU 的生命周期测试；
- 同一 worker 连续执行 3 个任务时 PID 不变、adapter load count 保持 1；
- release 默认等待运行锁，随后请求子进程退出，超时依次 TERM/KILL，并以子进程退出和显存 verifier 同时通过作为成功条件；
- Gateway 已提供单卡 `POST/GET/release` Compute session API、owner 隔离和 Idempotency-Key payload 冲突检查；
- `cancel_running` 未确认时由后端拒绝，任务目录和 cancel marker 均受服务端 storage root 约束。

本地自动化检查：

- `uv run ruff check .`：通过；
- `uv run pytest`：26 项通过；
- `git diff --check`：通过。

H100 真实验证（2026-07-31）：

- 每次运行前重新读取 inventory，最终动态选择 physical index 1、UUID `GPU-5cae32f8…`；选卡前无 compute PID，NVML 基线 478 MiB；
- Fast load + canonical warm-up：25.842 秒；ready 后稳定显存 56015 MiB；
- ready worker PID `3706671`，adapter load count 为 1；
- 同一 PID 连续执行 3 个 768×512、9 帧、24 FPS I2V，分别耗时 9.604、4.852、5.105 秒；峰值显存分别为 56335、56335、56334 MiB；
- 3 个结果均为独立 H.264/AAC MP4，时长 0.375 秒，文件大小分别为 175649、170258、174138 字节；
- 结果目录：`/data/oneiroi/ltx-2.3/outputs/oneiroi-worker-m2/m2-real-{1,2,3}/output/result.mp4`；
- release 未触发 TERM/KILL；子进程退出、显存回到 478 MiB、无 Oneiroi orphan process、选中 GPU 前后均无外部 compute PID；
- 首轮直接调用遗漏 `torch.inference_mode()` 曾触发 OOM；该缺陷由 `201c1bc` 修复，失败运行的 emergency release 和最终 NVML 检查均确认显存已回收；
- `e13bc0d` 将核心 Fast transformer 跨任务常驻；ready 显存和后续任务耗时证实任务间未重新构造 transformer。

未解决阻塞：无。

## M3：1–4 卡动态租约与 Compute session SSE

已验证实现：

- `InMemoryLeaseStore` 与 `RedisLeaseStore` 均以 GPU UUID 为键，使用 session ID、fencing token 和 TTL；Redis 获取使用单个 Lua 脚本保证候选选择与建租约原子化；
- 自动选卡按显存、利用率、温度和 UUID 稳定排序；手动模式只接受当前 inventory 中 eligible 的 UUID；
- 实际分配遵循 `min(requested, eligible, 4)`，`allowPartial=false` 时不足请求数不创建部分租约；
- balanced profile 对 1–4 卡分别生成 1F/0H、1F/1H、2F/1H、2F/2H，不要求 physical index 连续；
- 请求 4 卡但只有 physical index 0、2、7 可用的测试返回 3 卡、2 Fast + 1 HQ，外部占用 index 3 未被租约；
- 并发 session 竞争同一 UUID 的测试只允许一个成功，不产生双租约；
- Compute session 事件保存单调 event ID，SSE 支持 `Last-Event-ID` 后重放 slot/session ready、degraded、release 事件；
- heartbeat 丢失 reconcile 将具体 slot 标记为 `RUNNER_HEARTBEAT_LOST`，只清除对应 GPU lease，并将 session 置为 degraded 或 failed；
- Redis directed stream 命名固定为 `oneiroi:slot:{slot_id}:control`、`oneiroi:slot:{slot_id}:jobs` 和 `oneiroi:job:{job_id}:events`。

自动化检查：

- `uv run ruff check .`：通过；
- `uv run pytest`：33 项通过、Redis 集成项在普通运行中按环境开关跳过；
- `ONEIROI_TEST_REDIS=1 uv run pytest services/gateway/tests/integration/test_redis_leases.py`：1 项通过，使用既有 `127.0.0.1:6379`；
- `git diff --check`：通过。

H100 只读复核：测试后再次读取实时 inventory；本阶段未加载新 Model Worker、未租约或触碰外部占用卡。

未解决阻塞：无。

## M4：HQ profile、完整 PipelineSpec 与能力约束

已验证实现：

- `PipelineSpec` 改为不可变对象，identity 使用全部序列化字段的 SHA256；checkpoint、LoRA、Gemma revision、量化、offload、attention、compile 和 policy 任一变化都会生成新 identity；
- Fast/HQ profile builder 分别固定 Distilled 与 Dev + Distilled LoRA 资产，不以单一 `fast/hq` 字符串作为缓存键；
- `Ltx23HqAdapter` 只接受 HQ spec，HQ load/generate 失败保持 HQ 错误，不调用或降级到 Fast adapter；
- HQ adapter 通过官方 `TI2VidTwoStagesHQPipeline`、Dev checkpoint、0.25/0.5 两阶段 LoRA 强度、fp8-cast 和固定 guider 参数执行；
- `GET /v1/compute/capabilities` 返回 Fast/HQ 参数矩阵；一卡 session 的 HQ 原因固定为 `HQ_REQUIRES_AT_LEAST_2_GPUS`，两卡且 HQ slot ready 时才 available；
- Capability service 提供后端强制 `require_profile` 校验，供 M5 Job API 在提交前执行。

本地自动化检查：

- `uv run ruff check .`：通过；
- `uv run pytest`：38 项通过、1 项 Redis 集成按环境开关跳过；
- `git diff --check`：通过。

H100 真实验证（2026-07-31）：

- 实时 inventory 有 4 张 eligible GPU，满足 HQ 至少 2 卡的 session 前置条件；最终动态选择 physical index 2、UUID `GPU-6ff18a65…` 作为 HQ slot，基线 478 MiB；
- Dev/HQ PipelineSpec hash：`d0505a61391f7b9504a7cf277ab2489e812af75df51a5936f06e002cd0e88f51`；Dev checkpoint 和 Distilled LoRA SHA256 已在目标主机重新计算；
- HQ load + 768×512 canonical warm-up：39.827 秒；ready 显存 1269 MiB；
- 真实生产规格 I2V：1920×1088、121 帧、24 FPS、15 个 res2s step + 3 个 stage-2 step，耗时 165.607 秒，峰值 Torch 显存 27142 MiB；
- 输出 `/data/oneiroi/ltx-2.3/outputs/oneiroi-worker-m4/m4-hq-production/output/result.mp4`，H.264/AAC，5.041667 秒，1929491 字节；结果与既有 176 秒 HQ CLI 冷路径基线处于同一量级；
- HQ 使用 `AllocatorTrimStrategy.TRIM`，因为保留两个阶段的构建 state 会在 1080p stage-2 触发 OOM；该策略不降级 profile，仍使用 Dev checkpoint + HQ sampler，只在阶段间回收构建显存；
- release 未触发 TERM/KILL，子进程退出、NVML 回到 478 MiB、无 orphan PID；两次 OOM 调整过程均执行 emergency release 并确认显存回收。

未解决阻塞：无。
