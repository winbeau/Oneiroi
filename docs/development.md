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

树莓派部署/预览：

```bash
scripts/deploy-web-pi.sh --mode preview --host 0.0.0.0 --port 4173
```

当前 `pi5` 部署使用用户级 `oneiroi-studio.service`，可通过以下命令检查：

```bash
systemctl --user status oneiroi-studio.service
journalctl --user -u oneiroi-studio.service -f
```

Runner 可按 GPU UUID 启动 Supervisor；显式加载 slot 后会启动隔离的 Model Worker，并按 PipelineSpec 选择真实 Fast/HQ LTX adapter：

```bash
ONEIROI_RUNNER_NAME=runner-0 \
ONEIROI_RUNNER_QUEUE=fast \
ONEIROI_RUNNER_GPU_ID=GPU-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx \
ONEIROI_RUNNER_PHYSICAL_INDEX=0 \
uv run oneiroi-runner
```

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

1. 完成生产配置、鉴权边界、超时、OOM、审计与运行手册；
2. 按私网验收清单启动 Gateway、BFF 和 Runner；
3. 验证 GET、POST、PUT、SSE、真实 I2V、授权下载与 GPU release；
4. 确认所有服务只监听 `127.0.0.1`，不新增 Cloudflare、DNS 或路由入口。
