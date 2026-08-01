# 阶段 5：运维与质量体系

## 目标

让生产状态可被机器确认、故障可定位、发布可回滚、数据可恢复；不要求频繁重启，也不引入无必要的新基础设施。

## 当前已有

- Pi immutable `dist`、loopback Web/BFF、Cloudflare Tunnel。
- user systemd unit、linger、固定 release SHA、health 和回滚记录。
- H100 Gateway/BFF 由 Supervisor 管理。
- PostgreSQL、Redis、storage 和已有迁移。
- Ruff、pytest、前端 lint/typecheck/build 和 OpenAPI 生成命令。
- 当前 main 本地质量门通过。

## 当前缺口

### 发布事实

生产 runtime `fa7c28c` 与 main `60e6c1d` 不同。需要机器可读 manifest，避免把 main、历史 Runner 和生产模式混淆。

建议记录：

- Oneiroi repository SHA；
- Web build SHA；
- Pi/H100 runtime SHA；
- backend mode：unavailable / legacy-runner / gpu-server；
- gpu-server SHA/API version；
- Runner/model revision；
- database migration version；
- feature flags；
- 回滚 SHA。

### CI

当前 CI 未执行：

- `pnpm check:api`；
- Playwright E2E；
- 明确的 PostgreSQL/Redis integration job；
- gpu-server contract/integration；
- release manifest 校验。

当前 pytest 虽然 69 passed/5 skipped，但结束时出现未回收 `lease-renewal-*` task，应修复后再把测试视为干净通过。

另需处理 FastAPI 422 deprecation warning。

### 观测

需要统一：

- request/correlation ID；
- Oneiroi job ↔ remote job/lease/artifact ID；
- HTTP/SSE 延迟、重连次数和错误率；
- queue、Runner、GPU 和磁盘 admission；
- cancel latency、stuck job、lost job；
- artifact 下载/Range/完整性错误；
- service restart 和 release SHA。

### 数据与存储

- PostgreSQL backup/restore 和保留策略未产品化。
- Redis durable/ephemeral key 需要分类。
- attempt temp、partial artifact 和孤儿目录缺自动治理证据。
- 磁盘低水位 admission 需要落地；禁止自动删除未知 H100 文件。

### 配置与文档

- H100 Supervisor 配置目前不在 `infra/`。
- `docs/architecture.md`、README 与当前 gpu-server 决策存在漂移。
- Caddy 模板与当前 Node static origin 并存；应明确当前事实，不必为了文档一致强行安装 Caddy。

## 工作包

### A. 修复测试生命周期

- 找到未回收 lease renewal task 的测试路径。
- 所有 `ComputeSessionService` 在 fixture teardown 调用 `close()`。
- 增加断言：测试结束无 renewal/background task。
- 更新 FastAPI 422 常量。

### B. 加固 CI

最低门：

1. `pnpm check`
2. `pnpm check:api`
3. `uv run ruff check .`
4. `uv run pytest`
5. gpu-server contract tests
6. Playwright 稳定 smoke

PostgreSQL/Redis integration 可单独 job，不能依赖开发机残留服务。

### C. Deployment manifest

新增版本化 manifest 与验证命令：

- 部署前检查候选 SHA、工作区、migration 和 feature flag。
- 服务 health 输出 release/backend mode，但不输出 secret。
- 证据文档引用 manifest，不手工复制多份漂移事实。

### D. 日志和指标

- BFF/Gateway 使用结构化日志。
- 每个请求和 job 注入 correlation ID。
- gpu-server adapter 记录远端 ID、状态转换和耗时。
- 建立最小 dashboard/告警：API 5xx、SSE 重连、stuck job、Runner unavailable、磁盘低水位。

### E. Backup/cleanup/runbook

- PostgreSQL 定期备份和一次恢复演练。
- 明确 Redis key 的 TTL 和恢复策略。
- 只清理已知命名空间、已终态且超过保留期的 temp/partial。
- 任何清理先 dry-run 并记录数量/字节。
- 建立 Access、Pi Web/BFF、VPN、Gateway、gpu-server、Runner、storage 的故障 runbook。

### F. 配置纳管

- 将不含 secret 的 H100 Supervisor 模板放入 `infra/`。
- Secret 继续使用主机受限文件或 secret manager。
- 删除过时文档说法，明确 legacy Runner 仅为历史参考。

## 完成门

- CI 无 pending task 和 deprecation warning。
- OpenAPI drift、gpu-server contract 和至少一组 Playwright smoke 自动检查。
- 能用 manifest 确认生产 SHA/backend mode/model revision。
- 能从 Oneiroi job ID 定位完整跨服务日志。
- 数据库有可恢复备份证据。
- 磁盘低水位拒绝新任务，清理只作用于已知临时命名空间。
- 发布和回滚不要求隐式 pull/install/build，也不依赖日常重启。

## 预计时间

2–4 天，可与 adapter/产品阶段并行；若接入完整监控平台，时间另计。
