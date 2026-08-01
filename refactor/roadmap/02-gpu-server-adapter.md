# 阶段 2：gpu-server Adapter 加固

## 目标

把 `d88ae28` 的 happy-path HTTP adapter 提升为可恢复、可对账、可真机 canary 的 Fast adapter；保持 Oneiroi 产品 ownership，不把 scheduler 重新写回 Oneiroi。

## 当前代码状态

已实现：

- service token 和固定 client header。
- GPU inventory。
- lease create/renew/get/release 的基本调用。
- 输入 artifact upload。
- Fast job submit、状态 polling、取消和结果下载。
- 外部请求使用 artifact ID，不传服务器路径。
- 一个 MockTransport happy-path 测试。

默认关闭：`ONEIROI_GATEWAY_GPU_SERVER_ENABLED=false`。

## 关键缺口

1. `load_slot()` 无条件返回 ready，不验证 Runner/profile/model readiness。
2. `release_slot()` 无条件返回 true，远端 `releasing` 与本地 `released` 可能不一致。
3. lease TTL 参数被忽略，本地 expiry 固定 300 秒。
4. job 只依赖 idempotency key 重放，未持久化 remote job ID/event cursor。
5. 状态使用 0.5 秒 HTTP polling，没有 durable SSE。
6. artifact 下载不校验 SHA-256/size，也没有 `.partial` + 原子 rename。
7. 错误统一变成 `RuntimeError`，缺 retryable/non-retryable 分类。
8. 缺 401/409/429/5xx、timeout、取消竞争、重启恢复和 lease 测试。

## 工作包

### A. 冻结跨仓契约

与 gpu-server 明确定义：

- readiness/health；
- inventory DTO；
- lease create/get/renew/release 和状态机；
- job create/get/cancel；
- job SSE event schema、event ID、保留期、`Last-Event-ID`；
- artifact upload/head/download；
- SHA-256、size、media type；
- error code、HTTP status、retryability；
- idempotency key 保留期限和冲突语义；
- Runner/profile/model revision readiness；
- 磁盘低水位 admission。

### B. 明确远端映射的持久化

为 Oneiroi product job/attempt 保存：

- remote lease ID；
- remote job ID；
- idempotency key；
- last remote event ID；
- remote status/phase；
- output artifact ID、hash、size、media type；
- reconciliation timestamp 和 error。

不能只依赖进程内局部变量或 Redis 临时 mapping。

### C. 修正 compute/lease 语义

- 使用远端返回的 expiry，而不是固定 300 秒。
- `ready` 至少要求 lease active、Fast profile 可用、Runner 可执行或明确的 on-demand readiness。
- `release requested`、`releasing`、`released` 分离。
- 只有远端确认 released 后，本地才清理 lease/fencing/renewal。
- 远端 404、expired、lost 必须有明确 reconciliation 规则。

### D. SSE 优先、GET 对账

- 正常路径消费 gpu-server durable SSE。
- 持久化 last event ID。
- 断线使用 `Last-Event-ID` 重连。
- GET snapshot 只用于启动恢复、缺口对账和 SSE fallback。
- 禁止未知状态下自动创建新 attempt。

### E. Artifact 完整性

下载流程：

1. 写入 `.partial`。
2. 流式计算 SHA-256 和 size。
3. 与远端 metadata 对比。
4. `fsync` 后原子 rename 为最终 MP4。
5. 失败时只清理本次 partial。
6. 成功后由 Oneiroi 注册用户 asset。

上传也应验证服务返回的 artifact metadata，并记录 Oneiroi asset ↔ remote artifact 映射。

### F. 错误与重试模型

至少区分：

- authentication/authorization；
- admission/429；
- idempotency conflict/409；
- transient 5xx/timeout；
- runner unavailable；
- storage low-water；
- artifact mismatch；
- cancelled/timed_out/lost；
- unknown outcome requiring reconciliation。

只有明确 retryable 的操作才自动重试。

## 测试矩阵

### 单元/契约

- inventory 正常和 malformed DTO。
- lease acquire/renew/release/releasing/expired/404。
- 401、403、409、429、5xx、timeout。
- job create response 丢失后的 idempotent replay。
- cancel 与 succeed 竞争。
- SSE reconnect、重复 event、跳号和过期 cursor。
- artifact hash/size mismatch、下载中断和 partial cleanup。

### 集成

- `create_app(gpu_server_enabled=True)` 完整启动和关闭。
- PostgreSQL remote mapping 持久化。
- Gateway 在 queued/running/downloading 阶段重启。
- 每个 idempotency key 的远端 execution count 始终为 1。
- lease renewal task 在测试和 shutdown 时全部回收。

## 完成门

- Adapter 测试不再只有 happy path。
- pytest 不出现 pending task 泄漏。
- remote job ID、event cursor 和 artifact metadata 可持久恢复。
- Runner 不在线时不返回假 ready。
- release/cancel/unknown outcome 均有可对账状态。
- artifact 完整性校验通过后才标记 succeeded。

## 发布方法

先合并但保持开关关闭；单独选择 canary release SHA。禁止直接将当前 `main` 自动拉到 H100 并打开开关。

## 预计时间

2–4 天，取决于 gpu-server 契约和 SSE 是否已存在，不确定性约 ±50%。
