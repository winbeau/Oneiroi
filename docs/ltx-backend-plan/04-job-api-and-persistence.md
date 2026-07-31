# 任务调度、持久化、API 与安全边界

> 本文件是 [LTX-2.3 动态 H100 主计划](../ltx-desktop-inspired-backend-plan.md) 的模块子计划。跨模块范围、阶段顺序和里程碑以主计划为准。

## 调度与任务执行

### 不让 Runner 自由抢全局队列

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

### slot 选择

同 profile 的 ready slot 按以下顺序选择：

1. 当前空闲；
2. 已加载完全相同 PipelineSpec；
3. 最近分配时间最早；
4. 最近失败率最低；
5. UUID 稳定排序。

热加载模式下不应为普通 job 临时交换 profile。没有 HQ ready slot 时，HQ job 保持 queued 或返回 `HQ_NOT_READY`，不驱逐 Fast profile。

### 取消

- queued：Gateway 原子标记 cancelled，禁止后续 assignment；
- assigned 但未开始：向目标 slot 发送 cancel；
- generating：设置 cancel flag，在 diffusion callback/step 边界停止；
- hard cancel：只作为超时后的显式策略，通过终止 Model Worker 实现；该 slot 随后必须重新热加载。

### 失败和重试

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

## 数据模型

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

## API 草案

所有浏览器 API 继续使用 `/v1`，由 BFF 显式代理。

### Conversation CRUD 与幂等 PUT

Conversation 的 canonical state 迁移到 Gateway，BFF 只做身份注入和显式代理：

```http
POST /v1/conversations
GET  /v1/conversations
GET  /v1/conversations/{conversation_id}
PUT  /v1/conversations/{conversation_id}
```

`PUT` 完整替换当前允许修改的字段，首版只有 `title`：

```json
{
  "title": "更新后的创作会话"
}
```

重复提交相同 PUT 必须保持同一资源 ID，不创建新会话；非 owner 和不存在的资源都返回 404。该接口同时作为不暴露公网的 GET/POST/PUT 集成验证资源，详细测试边界见 [`07-private-api-validation.md`](./07-private-api-validation.md)。

### GPU inventory

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

### 后端能力与 profile

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

### 热加载

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

### 资源会话状态和事件

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

### 释放

```http
POST /v1/compute/sessions/{session_id}/release
```

```json
{
  "policy": "when_idle"
}
```

如果使用 `cancel_running`，必须由前端二次确认并由后端鉴权。

### Job API

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

## 输入、输出与安全边界

### 上传

当前前端把图片转为 Data URL 并持久化到 Zustand/localStorage，这不适合真实后端。改为：

1. 浏览器 multipart 上传到 BFF；
2. BFF 流式转发到 Gateway；
3. Gateway 校验大小、MIME、解码结果和尺寸；
4. 返回不可猜测 asset ID；
5. Job 只引用 asset ID，不接受服务器路径或任意 URL。

### 任务目录

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

### 下载

`GET /v1/jobs/{job_id}/file` 返回真实 MP4 或短时授权 URL，不再返回 JSON manifest。参数 manifest 可单独提供：

```http
GET /v1/jobs/{job_id}/manifest
```

### 身份

- 浏览器使用同源安全 cookie；
- BFF 从会话得到用户 ID；
- Gateway 只信任 BFF 签发的内部身份上下文；
- 原生 EventSource 不依赖自定义 `X-Oneiroi-User` header；
- 热加载/释放需要 `compute:manage` 权限；
- release 必须校验 owner/workspace 和活跃任务。

---

[返回主计划](../ltx-desktop-inspired-backend-plan.md)
