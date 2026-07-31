# GPU 动态分配、热加载与释放

> 本文件是 [LTX-2.3 动态 H100 主计划](../ltx-desktop-inspired-backend-plan.md) 的模块子计划。跨模块范围、阶段顺序和里程碑以主计划为准。

## GPU 与资源会话模型

### GPU 可用性判定

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

### 稳定标识

数据库和 Redis lease 使用 GPU UUID，不使用可重排的物理 index。API 可同时返回：

```json
{
  "id": "GPU-7f893bc3-...",
  "physicalIndex": 0,
  "name": "NVIDIA H100 80GB HBM3"
}
```

### 默认 1–4 卡 profile 分配

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

### 自动与手动选卡

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

## 模型 profile 与热加载语义

### Fast profile

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

### HQ profile

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

### 完整 PipelineSpec

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

### 热加载完成条件

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

### 释放流程

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

## 需要先做的测量

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

---

[返回主计划](../ltx-desktop-inspired-backend-plan.md)
