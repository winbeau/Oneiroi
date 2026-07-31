# 参考设计与 H100 验证基线

> 本文件是 [LTX-2.3 动态 H100 主计划](../ltx-desktop-inspired-backend-plan.md) 的模块子计划。跨模块范围、阶段顺序和里程碑以主计划为准。

## 已验证的 H100 基线

### 当前环境快照

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

### 已完成的冷启动 CLI 基准

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

### 当前 CLI 的正确定位

`scripts/run-ltx-2.3.sh` 和 `scripts/compare-ltx-2.3-quality.sh` 继续保留为：

- 人工 smoke test；
- 故障复现入口；
- 参数归一化和版本记录参考；
- Runner adapter 的回归基线。

生产任务不能继续“一任务启动一次 `python -m ltx_pipelines...`”，否则无法跨任务复用显存中的权重，也无法形成真正的热加载状态。

## 从 LTX Desktop 借鉴什么

官方 Desktop 后端的主链路是：

```text
FastAPI route
  → AppHandler
    → domain handlers
      → typed AppState
      → service protocols / heavy side effects
```

Oneiroi 应借鉴以下设计。

### 单一组合根与明确服务边界

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

### 显式资源槽和类型化状态机

Desktop 在 `state/app_state_types.py` 中将 GPU pipeline、CPU parked pipeline 和 generation 状态分开表示。Oneiroi 应保留这种“非法状态难以表示”的思路，但从单槽扩展为多 GPU slot，并把持久任务状态与进程内模型对象分开。

### 小锁区间

Desktop 的正确模式是：

1. 锁内检查和声明资源；
2. 锁外加载模型或执行推理；
3. 锁内重新校验并发布结果。

Oneiroi 的 Gateway 也不能在数据库事务或 Redis 分布式锁中执行几十秒的模型加载。租约只负责声明 GPU 所有权，真实加载在对应 Runner 上进行，通过事件更新状态。

### 模型驻留和确定性卸载

Desktop 会复用兼容 pipeline、交换 pipeline，并集中调用 GPU cleaner。Oneiroi 进一步增强为：

- 使用完整、不可变的 `PipelineSpec` 作为驻留缓存键；
- 一个 Model Worker 生命周期内只服务一个 profile；
- profile 切换通过退出旧子进程并启动新子进程完成；
- 释放按钮最终以进程退出为准，而不是只以 `empty_cache()` 返回为准。

### 后端发布能力，前端据此约束参数

Desktop 的 `/api/generate/models-specs` 让前端从后端获取可用模型、分辨率、FPS 和时长组合，并自动修正无效设置。Oneiroi 应增加统一 capabilities API，不能继续让前端写死 Fast/HQ、720p/1080p 或“有一张卡时仍能选 HQ”。

### 不直接照搬的部分

Desktop 面向单机单用户，因此有以下限制，不适合直接复制：

- 一个全局 GPU 槽；
- 一个全局 generation 状态；
- 长时间同步 `POST /api/generate`；
- 后台 daemon thread 无通用任务注册表；
- 取消主要是协作式检查；
- 模型缓存键没有覆盖所有 checkpoint/config 输入；
- renderer 本地恢复标记不是后端持久任务。

Oneiroi 必须使用异步 Job ID、持久任务记录、Runner 心跳、GPU 租约和可恢复事件流。

## 参考实现文件

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

---

[返回主计划](../ltx-desktop-inspired-backend-plan.md)
