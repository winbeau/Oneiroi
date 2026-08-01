# Oneiroi 后续路线图

> 审计基线：2026-08-01。该目录把“已部署事实、当前 main、历史验证和未来计划”分开记录，避免把代码存在误判为生产可用。

## 1. 当前结论

Oneiroi 已完成一个**安全可登录、具备会话/素材/任务产品模型的内部 beta 基座**；当前生产尚不能声称具备可用的真实视频生成链路。

### 版本事实

| 项目 | 当前事实 |
| --- | --- |
| 仓库 `main` / `origin/main` | `60e6c1dabe0f3301401dbb59d2b0d2e64c6cad06` |
| 生产 runtime | `fa7c28cc98edf423e2be8762ad13b55f606389eb` |
| main 中未部署的 gpu-server adapter | `d88ae28912f08d78fa1ca78d27f132abd9d1201f` |
| 当前 main 质量门 | Ruff、69 passed / 5 skipped、前端 lint/typecheck/build、OpenAPI 一致性通过 |
| 当前测试债 | pytest 结束时出现未回收 lease-renewal task；另有 FastAPI 422 deprecation warning |

生产继续冻结在 `fa7c28c` 是有意行为：`d88ae28` 仅是默认关闭的 Fast canary adapter，不应自动部署。

## 2. 进度按目标拆分

| 目标 | 估计完成度 | 判断 |
| --- | ---: | --- |
| 安全登录与生产入口 | 90% | Access、JWT、稳定 owner、服务断言、CSRF、immutable Web 已部署；缺两个真实 Authentik 用户验收 |
| 产品 Web 与数据闭环 | 75–85% | conversation、asset、job、SSE、取消、重试、下载、历史页面已实现；Agent/灵感仍偏原型 |
| Oneiroi 自有 Runner 工程 | 历史上接近完成 | M1–M8 有代码和实机记录，但当前生产不运行，且不再继续扩展 |
| gpu-server 接入 | 25–35% | HTTP happy path adapter 与一个 mock 测试已合并；真实契约、SSE、恢复、完整性和真机 canary 未完成 |
| 当前生产真实生成 | 0% 可用 | H100 没有 Oneiroi Runner/LTX inference；gpu-server adapter 未激活 |
| 运维与可观测性 | 50–60% | 固定 SHA、systemd/Supervisor、health、回滚已有；manifest、指标、备份、磁盘治理和完整 CI 未收口 |

这些百分比用于排期，不代表合同式验收结果。

## 3. 已完成能力的四类归档

### A. 已部署并实机验证

- Cloudflare Access 保护 `video.icthub.top/*`，未登录 challenge 和深链接回跳正确。
- BFF 验证 Access JWT 的 RS256、issuer、audience、expiry 和 JWKS。
- `(issuer, subject)` 稳定映射内部 owner；浏览器 cookie/header 不能冒充用户。
- Pi→H100 RSA 服务断言；H100 BFF/Gateway 无断言为 401。
- mutation Origin CSRF、请求体上限、SSE 和 Range 流式代理。
- React immutable static origin、loopback BFF、Cloudflare Tunnel、固定 release SHA。
- conversation、asset、job 的 owner 过滤；双测试 owner 交叉读取为 404。
- 图片上传、畸形图片 422、MP4/asset Range、删除和测试数据清理。
- Pi 一次 reboot 后服务恢复；历史 LAN/loopback preview 与 `lan-preview` 配置已删除。

### B. 当前 main 已有、生产未激活

- `GpuServerClient`、inventory、lease、compute、job executor 和 artifact HTTP adapter。
- Fast profile job submit/poll/cancel/download happy path。
- 默认 `ONEIROI_GATEWAY_GPU_SERVER_ENABLED=false`；没有生产部署或真机 canary 证据。

### C. 历史代码和实机验证成立、当前不运行

- Oneiroi 自有动态 GPU inventory、lease/fencing、Redis directed streams、Runner supervisor。
- LTX Fast/HQ、热加载/释放、任务恢复、取消和真实 MP4 生成记录。
- 这些能力仅作为迁移语义和回归参考，不应恢复为新的生产 scheduler 主线。

### D. 产品原型或静态体验

- Agent 面板当前使用本地模板拼接镜头建议，不是服务端 Agent。
- 灵感模板与搜索主要是前端静态内容。
- Playwright 场景存在，但当前 CI 未执行浏览器 E2E。

## 4. 路线图总览

| 顺序 | 阶段 | 优先级 | 预计时间 | 依赖 | 详细计划 |
| --- | --- | --- | --- | --- | --- |
| 1 | 真实身份验收 | P0 | 0.5–1.5 天 | 两个邀请账号、无权限测试账号 | [01-identity-acceptance.md](./01-identity-acceptance.md) |
| 2 | gpu-server adapter 加固 | P0 | 2–4 天 | gpu-server 契约与测试环境 | [02-gpu-server-adapter.md](./02-gpu-server-adapter.md) |
| 3 | LTX Fast 真机 canary | P1 | 1–3 天 | adapter 验收、Runner、H100、磁盘 admission | [03-fast-canary.md](./03-fast-canary.md) |
| 4 | 产品体验收口 | P1 | 2–4 天 | Fast 状态与错误契约稳定 | [04-product-experience.md](./04-product-experience.md) |
| 5 | 运维与质量体系 | P0/P1，可并行 | 2–4 天 | 生产配置和监控落点 | [05-operations-quality.md](./05-operations-quality.md) |

核心 Fast beta 预计 **6–12 个工作日**，不确定性约 ±50%；主要取决于 gpu-server Runner、SSE/幂等契约和 H100 真机环境。

## 5. 推荐执行节奏

### 第一周

1. 完成真实 Authentik 双用户和拒绝策略验收。
2. 修复当前测试 task 泄漏，将 `check:api` 纳入 CI。
3. 冻结 gpu-server lease/job/artifact/SSE/idempotency 契约。
4. 补齐 adapter 的 lease、恢复、错误、artifact 完整性测试。

### 第二周

1. shadow inventory/capability，不提交真实任务。
2. 单用户单任务 Fast canary，再测试取消、断网和 Gateway 重启。
3. 双用户串行 canary，确认 job/artifact/SSE 隔离。
4. 达到稳定门后再优化产品状态、Agent 和前端重连。

## 6. 总体验收门

只有同时满足以下条件，才能把项目称为“可邀请用户的真实生成 beta”：

- 两个真实 Authentik 用户全链隔离，无权限用户被拒绝。
- gpu-server 每个 idempotency key 只执行一次昂贵任务。
- Gateway/网络/SSE 中断后可对账，不盲目重复生成。
- Runner 不在线或磁盘低水位时明确拒绝，不显示假 ready/假成功。
- 输出 artifact 的 ID、SHA-256、size、media type 校验一致后才标记 succeeded。
- 连续 10 个 Fast job 至少 9 个成功，失败均有可操作错误。
- 取消最终收敛，不长期停在 `cancel_requested`。
- Pi/H100 继续使用明确的 runtime SHA、backend mode 和回滚点。

## 7. 明确不做

- 不继续扩展 Oneiroi 自有 GPU scheduler/Runner 作为生产主线。
- 不直接把当前 main 自动部署到生产。
- 不在第一轮 Fast canary 同时开放 HQ。
- 不把浏览器可提供的身份、路径或 service token 当作可信输入。
- 不因磁盘低水位自动删除未知 H100 文件。
- 不在生成链稳定前进行 GitHub transfer 或大范围仓库重写。
