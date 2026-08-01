# LTX 动态 H100 实施进度

> 只记录已经由代码、自动化测试或目标主机只读检查验证的事实。里程碑提交使用本文件所在提交或后续阶段补录的 Git hash 标识。

## 当前状态

| 阶段 | 里程碑 | 状态 | 对应提交 |
| --- | --- | --- | --- |
| P0 | M1 资源可见 | 已完成 | `e5af69e` |
| P1 | M2 Fast 生命周期 | 已完成 | `b3956fd`、`4e5299f`、`201c1bc`、`e13bc0d` |
| P2 | M3 动态调度 | 已完成 | `3304dba` |
| P3 | M4 HQ 能力 | 已完成 | `00dacc9`、`375fc95`、`fcae104`、`af38b3a` |
| P4 | M5 真实任务 | 已完成 | `04473ee` |
| P5 | M6 前端闭环 | 已完成 | `8cf26cf` |
| P6 | M7 生产加固 | 已完成 | `c3bbb6a` |
| P7 | M8 私网 API 验证 | 已完成 | M8 本文件所在提交 |

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

## M5：PostgreSQL 任务、Redis 定向流、薄 BFF 与真实资产

已验证实现：

- Gateway 成为 Conversation canonical state，提供 POST/GET/list/幂等 PUT；非 owner 和不存在资源统一 404，Pydantic 对空/超长 title 返回 422；
- 新增 multipart image upload，限制 MIME/大小并用 Pillow 解码验证，客户端只能引用 asset ID，不能提交服务器路径；
- `jobs`、`job_attempts`、`job_events` 和 `assets` repository 同时提供内存测试实现与 SQLAlchemy/PostgreSQL 实现；retry 在同一 job 下新增 attempt，不覆盖历史 attempt/event；
- Alembic `0001_dynamic_backend` 创建 conversations、compute_sessions、gpu_slots、model_profiles、assets、jobs、job_attempts 和 job_events；
- Gateway 先从 ready profile slot 做单任务互斥 reservation，再写入 `oneiroi:slot:{slot_id}:jobs`；Redis 不是最终业务状态源；
- Job API 覆盖 create/list/get/SSE/cancel/retry/file/manifest；状态区分 `cancel_requested` 与 `cancelled`，事件先持久化再通知 SSE；
- `/file` 返回授权后的 `video/mp4`，`/manifest` 独立返回且过滤内部 `*path` 字段；owner 隔离覆盖 snapshot、asset 和下载；
- 本地 fake executor 仅由测试显式注入并生成可探测 H.264 MP4；生产默认 executor 为 `None`，不会静默模拟成功；
- Pi BFF 删除 `StudioStore` 生产接线和 timer 模拟，改为显式 Gateway 路由、身份转发、上传上限、SSE/下载代理和 503 受控映射。

自动化与基础设施检查：

- `uv run ruff check .`：通过；
- `uv run pytest`：47 项通过、2 项外部依赖集成按环境开关跳过；
- PostgreSQL + Redis 开关全部启用时：49 项通过；
- `alembic upgrade head` 在 `127.0.0.1:5432` 的 PostgreSQL 16 成功，`alembic current` 为 `0001_dynamic_backend (head)`；
- Redis Lua lease 集成测试在 `127.0.0.1:6379` 通过；测试使用唯一 key 并清理；
- Gateway/BFF 进程内完整链验证 Conversation PUT、upload、Compute session、job SSE、授权 MP4、manifest、cancel 和 retry；
- `git diff --check`：通过。

真实资产基线：M2 Fast 和 M4 HQ 已输出真实 LTX MP4；M5 的真实 Gateway → Model Worker HTTP 链在最终 M8 私网验证中执行，不以测试 fake 结果替代该最终验收。

未解决阻塞：无。

## M6：Compute UI、真实前端状态与 OpenAPI 契约

已验证实现：

- WebUI 服务端状态迁移到 TanStack Query：Conversation、Job、Asset、GPU inventory、capability 和 Compute session 均以 Gateway/BFF snapshot 为准；Zustand 只保留 Composer 草稿、active conversation/session ID 与 UI 展开状态；
- 新增 ComputeControl、GPU selector、session/slot 面板和 release dialog，覆盖自动/手动选卡、默认 4 卡、partial allocation、balanced Fast/HQ 预览、逐 slot 加载状态和释放策略；
- Composer 从 `/v1/compute/capabilities` 渲染参数矩阵；无 ready session 时禁用生成，一卡 session 的 HQ 在前端显示后端原因并禁用，不会静默降级为 Fast；
- 上传、Conversation 创建、I2V 提交、取消、重试、授权视频和资产页面全部使用真实 API；Job SSE 更新 assignment、phase、step、attempt、warm start、output 和 error；
- 生产模式删除浏览器 timer/持久化 Job fallback，API 失败明确显示不可用且不产生假成功；仅 `VITE_DEMO_MODE=true` 启用带显式标识的本地 Demo adapter；
- Playwright API mock 覆盖 Compute load、HQ gating、SSE 成功、release、Gateway 失败不伪造成功、模板/Agent 和移动端 sidebar；
- Gateway capability route 增加明确的 Pydantic response model；`scripts/export-gateway-openapi.py` 导出 OpenAPI，`openapi-typescript` 生成前端 DTO，Compute/Job/Asset/Conversation response 类型不再手写重复定义；
- `docs/development.md` 已更新真实 API、Demo mode、Runner 和 OpenAPI 生成流程。

自动化检查：

- `pnpm generate:api`：成功导出 `apps/web/openapi/gateway.json` 并生成 `apps/web/src/generated/gateway.ts`；
- `pnpm check`：ESLint、TypeScript 和生产构建全部通过；
- `uv run ruff check .`：通过；
- `uv run pytest`：47 项通过、2 项外部依赖集成按环境开关跳过；PostgreSQL + Redis 开关全部启用时 49 项通过；
- `pnpm --filter @oneiroi/web e2e`：Chromium 与 mobile Chromium 合计 9 项通过、1 项按 desktop/mobile 条件跳过；
- `git diff --check` 与敏感文件模式扫描：通过。

未解决阻塞：无。

## M7：Redis Runner 执行链、故障恢复与生产边界

已验证实现：

- Gateway 使用 Redis bootstrap/per-slot streams 下发完整 PipelineSpec、job 和 unload；Runner 通过稳定 consumer 恢复未 ACK 消息，command result 使用 command ID 幂等缓存；
- lease fencing token 进入 load/job/unload 全链，Runner 拒绝 stale token；Redis lease 周期续租，release 使用 Lua compare-and-delete，旧 session 不能删除重新取得的 lease；
- release 只有在 Model Worker 退出且 NVML 显存验证通过后才清 lease；显存未回落时 slot/session 显式失败并继续续租；
- Runner 在真实 adapter load 前校验 checkpoint、upsampler、LoRA SHA256 和 Gemma 目录；完整 PipelineSpec identity 新增 LoRA hash；
- Compute session/slot snapshot 持久化到 PostgreSQL；Gateway 重启通过 PostgreSQL + live Redis lease 恢复 session、slot 和 fencing token；非终态 Job 重新附着 Redis event stream；
- job attempt 在 succeeded/failed/cancelled 时写入 terminal status、finished time、worker PID、warm start、峰值显存和生成耗时；
- Runner heartbeat monitor 自动处理 heartbeat loss；Redis dispatch/renewal 不可用均产生明确错误，不留下 busy slot 或伪装 ready；
- 默认 24 小时 Compute idle TTL 使用 `when_idle` 自动释放；4 slot 并发容量测试确认每卡最多一个任务；
- 故障测试覆盖 OOM 后 Worker 复用、子进程崩溃、unload TERM escalation、stale release、外部占用 GPU、Gateway restart 和 Redis failure；
- production BFF 只接受可信 cookie identity，production Gateway 拒绝空身份；Compute create/release 使用 owner hash 审计；production Runner 拒绝 root 用户；
- 详细验证记录见 `docs/ltx-backend-plan/m7-reliability-validation.md`。

自动化检查：

- `uv run ruff check .`：通过；
- `uv run pytest`：不启用外部依赖时通过，PostgreSQL + Redis 开关全部启用时 68 项通过；
- Redis Gateway → fake Runner → Model Worker → Job event → release 集成链通过，并验证错误 fencing token 被拒绝；
- PostgreSQL active Compute session restore、inflight Job 恢复和 attempt terminal persistence 通过；
- `pnpm check`、`git diff --check` 和敏感文件模式扫描：通过。

真实 H100：本阶段只完成故障/容量自动化，不加载真实模型；真实 loopback Fast I2V 和 release 在 M8 执行。

未解决阻塞：无。

## M8：私网 GET/POST/PUT/SSE、真实 Fast I2V 与 release

已验证实现与部署修复：

- `scripts/test-private-api.sh` 在 production BFF 上覆盖 health、capabilities、Conversation POST/GET/重复 PUT、owner 隔离、422、GPU inventory、Compute session、Compute SSE、图片上传、Job SSE、授权 MP4/manifest 和 release；
- Gateway/BFF 只监听 `127.0.0.1:18010/18000`，Redis/PostgreSQL 只监听 loopback；目标为禁用 Docker、无 systemd 的 Ubuntu 24.04 容器，验证未创建 Cloudflare、DNS、NAT 或公网入口；
- production Gateway/BFF 的无身份请求均返回 401；BFF private Gateway client 禁止继承目标容器 proxy 环境；
- 修复全局 `.gitignore` 误排除 Gateway `db/models` 源码的问题，目标机干净 checkout 可以执行 Alembic `0001_dynamic_backend (head)`；
- public manifest 删除所有 path-bearing 字段，包括可能包含 LoRA 文件名的 `loraPathsAndScales`；
- Runner 在 load 前后验证 live Redis lease 的 session/fencing token，迟到 bootstrap command 无法在 lease 释放后加载模型；
- 详细记录见 `docs/ltx-backend-plan/m8-private-api-validation.md`。

真实 H100 loopback 验证（2026-08-01）：

- 8 张 H100 中 physical index 0、1、2、7 eligible；3–6 保持外部占用和不可分配，未被租约或终止；
- 单卡 auto 最终选择 physical index 1、UUID `GPU-5cae32f8…`，1 Fast + 0 HQ；Compute snapshot/SSE ready，一卡 HQ 原因固定为 `HQ_REQUIRES_AT_LEAST_2_GPUS`；
- cold Fast worker load 64.864 秒，adapter load count 1；真实 1280×704、121 帧、24 FPS I2V 生成耗时 19.521 秒，峰值显存 60313 MiB；
- Job SSE 持久化 `job.queued → job.assigned → job.updated → job.succeeded`；授权 MP4 为 5.041667 秒、3217250 bytes，`ffprobe` 确认为 MP4 container；
- release 返回 `released`，slot 为 `empty`，选中 GPU 显存从 0 MiB 回到 0 MiB，eligible 0/1/2/7 无 compute PID；
- 临时 Gateway/BFF/Runner、M8 数据库行、Redis key、上传副本和生成媒体均已清理，API 测试端口已关闭。

最终自动化检查：

- `uv run ruff check .`：通过；
- PostgreSQL + Redis 开关全部启用时 `uv run pytest`：69 项通过；
- `pnpm check`：通过；
- `pnpm --filter @oneiroi/web e2e`：9 项通过、1 项按条件跳过；
- `bash -n scripts/test-private-api.sh`、`git diff --check`：通过。

部署边界：目标 SSH 容器身份为 root，因此真实 M8 Runner 使用 development process mode；production Runner 拒绝 root 已在 M7 验证，正式容器必须使用专用非 root `USER`，不能关闭该保护。

未解决阻塞：无。

## M9：首尾帧、热复用与 lease 自动卸载

2026-08-02 在 H100 loopback 上补充验证首帧+尾帧产品链路，并修复 gpu-server 的 managed PID 与 stale-fence release：

- Oneiroi 5 秒 Fast I2V 输出 H.264 1280×704、121 帧，首输出更接近首输入、尾输出更接近尾输入；
- 同 lease/profile 的第二个真实 job 复用同一模型 child PID，不再被 NVML 误判为 foreign process；
- lease release 后 worker 自动卸载 child，GPU 回到 0 MiB，attempt temp 和 managed PID registry 清空；
- 完整证据见 `docs/ltx-backend-plan/m9-first-last-gpu-server-e2e.md`。

未解决阻塞：无。
