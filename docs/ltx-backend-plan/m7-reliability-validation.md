# M7 可靠性与生产加固验证

## 实现范围

- Gateway 通过 Redis bootstrap/per-slot streams 向固定 GPU Runner 发送完整 `PipelineSpec`、job、cancel 和 unload 命令，并等待带 command ID 的结果；
- Runner 使用稳定 consumer name 恢复未 ACK 消息，命令结果保留幂等缓存，job/control 都校验 lease fencing token；
- Runner 只在 Model Worker 子进程导入 Torch/LTX；真实 adapter load 前验证 checkpoint、upsampler、LoRA SHA256 及 Gemma 目录；
- Redis GPU lease 支持周期续租，release 使用 Lua compare-and-delete，旧 session 不能删除重新取得的 lease；
- release 后只有子进程退出且 NVML 显存验证通过才清理 lease；显存未回落时继续续租，避免 GPU 被二次分配；
- Compute session/slot snapshot 写入 PostgreSQL，Gateway 启动时从 PostgreSQL + live Redis lease 恢复 fencing token 和 active session；
- 非终态 Job 在 Gateway 重启后重新附着 per-job Redis event stream，attempt 终态、worker PID、warm start、峰值显存和耗时写回 repository；
- Runner heartbeat monitor 在超时后将 slot 标记 `RUNNER_HEARTBEAT_LOST` 并只释放对应 lease；Redis 短暂不可用不会让 monitor 进程退出；
- Compute session 默认 24 小时 idle TTL，过期使用 `when_idle` release；
- Redis dispatch 失败会持久化 `DISPATCH_FAILED` 并释放 slot，不留下 assigned/busy orphan；
- production BFF 只接受可信 cookie identity，忽略开发 header；production Gateway 拒绝空 identity；Compute create/release 写入去敏审计日志；
- production Runner 拒绝 root 身份。

## 故障与容量覆盖

| 场景 | 验证 |
| --- | --- |
| 4 个并发 Fast/HQ job | 4 个 slot/GPU 各分配一次，第 5 个任务被拒绝，不双分配 |
| Runner 子进程崩溃 | Supervisor 棄测 EOF，release 后无 child PID |
| Redis dispatch 不可用 | Job 进入 retryable `DISPATCH_FAILED`，slot 回到 ready |
| Redis lease renewal 不可用 | Session 进入 `REDIS_LEASE_RENEWAL_FAILED`，不伪装 ready |
| 外部进程占用 GPU | inventory/manual selection 已拒绝 `foreign_busy` GPU |
| CUDA OOM | 单 Job 返回 `CUDA_OUT_OF_MEMORY`，Worker 可继续完成下一任务 |
| unload timeout | Supervisor 先 TERM，必要时 KILL，并记录 escalation |
| Gateway 重启 | active Compute session、fencing token 和 inflight Job 恢复并完成 |
| Runner heartbeat 丢失 | 对应 slot error、session degraded/failed、对应 lease 清理 |
| 24 小时 idle | 测试用短 TTL 验证自动 release 和 lease 清理 |
| stale release | 旧 session 无法删除新 session 的 Redis lease |

## 自动化结果

2026-07-31：

- `uv run ruff check .`：通过；
- `ONEIROI_TEST_POSTGRES=1 ONEIROI_TEST_REDIS=1 uv run pytest`：68 项通过；
- Redis Gateway → fake Runner → Model Worker → Job event → release 集成链通过；
- PostgreSQL active Compute session restore 与 Job/attempt/event 持久化通过；
- 本阶段未加载真实 H100 模型；真实 Fast I2V、SSE、下载、NVML baseline 和 release 由 M8 私网 loopback 验收执行。

## 生产配置边界

启用真实 Runner backend 时必须同时启用 Redis leases，并提供完整模型路径和 SHA256：

```text
ONEIROI_GATEWAY_REDIS_LEASES_ENABLED=true
ONEIROI_GATEWAY_REDIS_JOB_STREAMS_ENABLED=true
ONEIROI_GATEWAY_REDIS_RUNNER_BACKEND_ENABLED=true
ONEIROI_GATEWAY_PERSISTENCE_ENABLED=true
ONEIROI_GATEWAY_LTX_*=...
```

每个 Runner 使用唯一、稳定的 `ONEIROI_RUNNER_NAME` 和 GPU UUID；`ONEIROI_RUNNER_STORAGE_ROOT` 必须与 Gateway storage root 的 `jobs/` 子目录指向同一受控文件系统。
