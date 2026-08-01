# M8 私网 API 与真实 Fast I2V 验证记录

验证日期：2026-08-01  
目标：H100 实验室容器，8 × NVIDIA H100 80GB HBM3  
范围：仅 loopback；未新增 Cloudflare、DNS、NAT、端口转发或公网入口

## 1. 服务与监听面

- 目标环境是无 systemd、禁用 Docker 的 Ubuntu 24.04 容器；验证过程未调用 Docker。
- PostgreSQL 与 Redis 作为容器内进程提供服务，分别只监听 `127.0.0.1/::1:5432` 和 `127.0.0.1/::1:6379`。
- Gateway 以 production 配置监听 `127.0.0.1:18010`；BFF 以 production 配置监听 `127.0.0.1:18000`。
- production Gateway 对缺失 `X-Oneiroi-User` 的受保护接口返回 401；production BFF 对缺失可信身份 cookie 的请求返回 401。
- BFF 到 Gateway 的 HTTP client 固定 `trust_env=False`，loopback 请求不继承目标容器的 SOCKS/HTTP proxy 环境。
- `ss -ltnp` 验证两个 API 端口只绑定 `127.0.0.1`，未出现 `0.0.0.0` 或 `[::]` API listener。
- 验证结束后已停止临时 Gateway、BFF 和全部 Runner；`18000/18010` listener 均消失。

目标 SSH 容器的登录身份是 root，因此真实 M8 Runner 使用 development process mode；production Runner 拒绝 root 的边界已在 M7 自动化验证。正式部署仍必须让容器以专用非 root `USER` 运行 Runner，不能关闭该检查。

## 2. 数据与基础设施

- Alembic `upgrade head` 在目标 PostgreSQL 成功；`current` 为 `0001_dynamic_backend (head)`。
- `oneiroi` 数据库使用 `oneiroi` owner，通过 TCP loopback 登录、临时表写入和读取验证。
- Redis 返回 `PONG`，`protected-mode=yes`，bind 为 `127.0.0.1 -::1`。
- M8 暴露并修复了 `.gitignore` 的全局 `models/` 规则误排除 `oneiroi_gateway/db/models/*.py` 的问题；目标机从干净 Git checkout 可以导入 SQLAlchemy models 并执行迁移。
- 验证结束后已删除 M8 owner 的 Conversation、Compute、Job、Attempt、Event 和 Asset 记录，清理 `oneiroi:*` Redis key，并删除 M8 上传副本、日志和生成媒体目录。

## 3. 非 GPU GET、POST、PUT 链

`scripts/test-private-api.sh` 在 production BFF `http://127.0.0.1:18000` 上通过：

- `GET /healthz`；
- `GET /v1/compute/capabilities`；
- `POST /v1/conversations`；
- 对同一 Conversation 连续两次执行相同 `PUT /v1/conversations/{id}`；
- `GET` detail/list 验证 ID 唯一且最终 title 正确；
- 错误 owner 读取返回 404；
- 空 title PUT 返回 422。

目标容器只有 `python3`，脚本支持 `ONEIROI_PRIVATE_API_PYTHON` 并默认使用 `python3`，不依赖额外的 `python` alias。

## 4. GPU inventory、Compute 与 SSE

实时 inventory：

- 8 张 H100 均以稳定 `GPU-...` UUID 返回；
- eligible physical index 为 0、1、2、7；
- physical index 3–6 有约 14 GiB 外部显存占用并保持 `eligible=false`；
- 验证只为 0、1、2、7 启动固定 UUID Runner，未向 3–6 写命令、创建租约或终止进程。

最终单卡 auto session：

- 请求 1 卡、`selectionMode=auto`、`profilePolicy=balanced`；
- 自动选择 physical index 1、UUID `GPU-5cae32f8…`；
- profile plan 为 1 Fast + 0 HQ；
- Compute snapshot 与 SSE 均观察到 ready；
- 一卡 capabilities 中 Fast 可用，HQ 明确返回 `HQ_REQUIRES_AT_LEAST_2_GPUS`。

验证过程中发现：若某个 eligible GPU 没有对应 Runner，auto session 会正确失败为 `RUNNER_HEARTBEAT_LOST`。随后又验证并修复了更严格的迟到命令场景：Runner 在 load 前后都从 Redis 校验当前 session/fencing lease，lease 已释放的旧 bootstrap command 返回 `FENCING_TOKEN_MISMATCH`，不能迟到加载模型或留下无租约显存。

## 5. 真实 Fast I2V 链

通过 production BFF 执行：

1. multipart 上传真实首帧；
2. `POST /v1/jobs/i2v` 创建 Fast Job；
3. Job SSE 观察到 `job.queued → job.assigned → job.updated → job.succeeded`；
4. snapshot 终态为 `succeeded`；
5. 授权下载 MP4 与 public manifest；
6. `ffprobe` 验证 MP4 container；
7. release Compute session 并验证 GPU 回收。

去敏后的真实结果：

- session：`compute-01df932b…`；
- job：`job-44d2a922…`；
- profile：`ltx23-distilled-fast-v1`；
- physical index：1；
- cold worker load：64.864 秒，adapter load count 1；
- worker PID：`4151969`，release 后已退出；
- 请求规格：1280×704、121 帧、24 FPS、5 秒、seed 42、`fp8-cast`、`offload=none`；
- 生成耗时：19.521 秒；
- 峰值显存：60313 MiB；
- MP4 duration：5.041667 秒；
- MP4 size：3217250 bytes；
- manifest 不包含 `checkpointPath`、`upsamplerPath`、`loraPathsAndScales` 或其他 path-bearing 字段。

## 6. Release 与外部 GPU 保护

- `POST /v1/compute/sessions/{id}/release` 返回 `released`；slot 终态为 `empty`。
- 选中 GPU 的 NVML 显存从基线 0 MiB 回到 0 MiB。
- release 后 eligible GPU 0、1、2、7 均为 0 MiB、0% utilization，且无 compute PID。
- 外部占用 GPU 3–6 的显存仍分别约为 14597、14155、14093、14233 MiB；没有执行 kill、reset 或 lease 操作。
- 临时 Runner 退出后再次检查无 Oneiroi CUDA orphan process。

## 7. M8 期间修复的真实部署缺陷

- `5ebf0ca`：解除 Gateway SQLAlchemy `db/models` 源码被 `.gitignore` 误排除的问题。
- `61f594e`：BFF 私网 Gateway client 禁止继承 proxy 环境。
- `aa5730e`、`54742ca`：新增可重复的 private API smoke script，并兼容只有 `python3` 的容器。
- `0254f99`：public manifest 删除所有 path-bearing 字段，包括 LoRA path 数组。
- `af7e5db`：Runner load 前后验证 live Redis lease，拒绝迟到或失效 fencing command。

## 8. 最终回归

- `uv run ruff check .`：通过；
- PostgreSQL、Redis 集成开关全部启用的 `uv run pytest`：69 项通过；
- `pnpm check`：ESLint、TypeScript 和 production build 通过；
- `pnpm --filter @oneiroi/web e2e`：9 项通过，1 项按项目条件跳过；
- `bash -n scripts/test-private-api.sh`：通过；
- `git diff --check`：通过；
- loopback GET/POST/PUT/SSE/upload/Fast I2V/download/manifest/release：通过。

M8 不创建公网发布能力。后续若部署到正式容器，必须保留 loopback/可信私网监听边界，并使用专用非 root Runner 用户。
