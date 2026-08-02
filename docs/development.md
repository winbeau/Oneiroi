# 本地开发

## 1. 安装依赖

```bash
cp .env.example .env
pnpm install
uv sync --all-packages
```

uv workspace 统一生成根目录 `uv.lock`，pnpm workspace 统一生成根目录 `pnpm-lock.yaml`。不要在子目录混用 npm、yarn、pip 或 poetry。

## 2. 启动依赖服务

```bash
docker compose up -d postgres redis
docker compose ps
```

Compose 端口仅绑定 `127.0.0.1`。生产环境不得直接沿用本地密码，也不得把 Redis/PostgreSQL 映射到公网接口。

## 3. 启动应用

分别打开终端：

```bash
uv run uvicorn oneiroi_gateway.main:app --reload --port 8010
uv run uvicorn oneiroi_bff.main:app --reload --port 8000
pnpm dev
```

检查：

- WebUI: `http://localhost:5173`
- BFF health: `http://localhost:8000/healthz`
- Gateway health: `http://localhost:8010/healthz`

WebUI 默认只调用同源 BFF。BFF/Gateway 不可用时，生产模式会明确显示错误并保持“生成”禁用，不会在浏览器内伪造成功任务或资产。只有显式设置 `VITE_DEMO_MODE=true` 时才启用带 `Demo mode` 标识的本地演示 adapter：

```bash
VITE_DEMO_MODE=true pnpm dev
```

工作区内网调试：

```bash
pnpm dev:host
# http://<本机内网IP>:5173
```

Pi5 内网一键部署使用完整 edge 脚本，而不是直接运行 Web foreground 命令：

```bash
cd ~/oneiroi-studio
scripts/deploy-pi.sh lan --host 192.168.3.250 \
  --gateway-url http://10.30.176.95:18000
```

脚本会先停止并禁用 `cloudflared-video.service`，再 fast-forward、frozen install、构建 immutable Web、备份现有 env/unit、将 BFF 切到 development identity、安装并重启 BFF/Web user services，最后验证 loopback BFF 和 LAN origin health。`bff.env` 必须预先包含 Pi→H100 service assertion 私钥配置；脚本只更新模式、Gateway、Origin 和 timeout，不创建或打印凭据。重复部署时可省略 `--gateway-url` 以保留当前值。

树莓派安全生产部署：

1. Pi BFF 使用 `Cf-Access-Jwt-Assertion` 验证 Cloudflare Access JWT，并把 `(issuer, subject)` 映射成稳定 owner；不要设置或恢复 `ONEIROI_API_PROXY_USER`。
2. Pi BFF 用只读配置文件中的 RSA 私钥签发短时服务断言；H100 BFF 和 Gateway 只接受该断言，不接受浏览器伪造的 `X-Oneiroi-User`。
3. 用 `infra/systemd/user/oneiroi-bff.service` 和 `oneiroi-web.service` 部署；web unit 只运行已经构建的 immutable `dist/`，不在启动时 pull/install/build。

```bash
# 先由 Cloudflare Access 应用配置提供这三个非 secret 参数
export ONEIROI_BFF_ACCESS_ISSUER=https://<team>.cloudflareaccess.com
export ONEIROI_BFF_ACCESS_AUDIENCE=<access-application-audience>
export ONEIROI_BFF_ACCESS_JWKS_URL=https://<team>.cloudflareaccess.com/cdn-cgi/access/certs

# 同源静态 origin；BFF target 只应是 loopback
ONEIROI_BFF_TARGET=http://127.0.0.1:8000 \
scripts/deploy-web-pi.sh --mode static --host 127.0.0.1 --port 4173 \
  --release-sha <release-sha>
```

`ONEIROI_API_PROXY_TARGET` 仅供本地 Vite dev/preview 使用；它不再注入用户 cookie。公网部署必须由 BFF 验证 Access JWT，未配置 issuer/audience/JWKS 或服务断言密钥时应拒绝请求。

当前 `pi5` 部署使用用户级 `oneiroi-studio.service`，生产配置应迁移到仓库内的 `infra/systemd/user/` unit，可通过以下命令检查：

```bash
systemctl --user status oneiroi-studio.service
journalctl --user -u oneiroi-studio.service -f
```

真实 Gateway → Redis → Runner 模式必须同时启用 PostgreSQL、Redis leases、job streams 和 Runner backend，并提供 `.env.example` 中全部 `ONEIROI_GATEWAY_LTX_*` 路径/SHA256。缺少 profile 字段时 Gateway 启动即失败，不会用未知模型继续运行。

Runner 可按 GPU UUID 启动 Supervisor；显式加载 slot 后会启动隔离的 Model Worker，并按 PipelineSpec 选择真实 Fast/HQ LTX adapter。storage root 必须是 Gateway storage root 的 `jobs/` 子目录：

```bash
ONEIROI_RUNNER_ENVIRONMENT=production \
ONEIROI_RUNNER_NAME=runner-0 \
ONEIROI_RUNNER_QUEUE=fast \
ONEIROI_RUNNER_GPU_ID=GPU-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx \
ONEIROI_RUNNER_PHYSICAL_INDEX=0 \
ONEIROI_RUNNER_STORAGE_ROOT=/data/oneiroi/storage/jobs \
uv run oneiroi-runner
```

生产 Runner 拒绝 root 身份。Redis 命令携带 fencing token；Runner 不接受旧 session 的 job、cancel 或 unload。Gateway 默认每 100 秒续租 300 秒 lease，并在 24 小时无任务后执行 `when_idle` release。

## 4. 检查

```bash
pnpm generate:api
pnpm check:api
pnpm check
uv run ruff check .
uv run pytest
pnpm --filter @oneiroi/web e2e
```

`pnpm generate:api` 从 Gateway Pydantic/OpenAPI 导出 `apps/web/openapi/gateway.json`，再生成 `apps/web/src/generated/gateway.ts`。API DTO 变更后必须重新生成并提交；CI 使用 `pnpm check:api` 检查漂移。

## 5. 当前后续顺序

1. 按私网验收清单启动 Gateway、BFF 和 Runner；
2. 验证 GET、POST、PUT、SSE、真实 I2V、授权下载与 GPU release；
3. 确认所有服务只监听 `127.0.0.1`，不新增 Cloudflare、DNS 或路由入口。
