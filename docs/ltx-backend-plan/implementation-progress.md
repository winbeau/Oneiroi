# LTX 动态 H100 实施进度

> 只记录已经由代码、自动化测试或目标主机只读检查验证的事实。里程碑提交使用本文件所在提交或后续阶段补录的 Git hash 标识。

## 当前状态

| 阶段 | 里程碑 | 状态 | 对应提交 |
| --- | --- | --- | --- |
| P0 | M1 资源可见 | 已完成 | M1 本文件所在提交 |
| P1 | M2 Fast 生命周期 | 未开始 | — |
| P2 | M3 动态调度 | 未开始 | — |
| P3 | M4 HQ 能力 | 未开始 | — |
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
