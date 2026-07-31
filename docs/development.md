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

WebUI 会优先调用同源 BFF；BFF 未启动时自动退回浏览器内的演示任务流，仍可验收灵感模板、首尾帧、参数、任务阶段和资产复用。Prompt 包含 `[fail]` 时可测试可恢复失败卡片。

工作区内网调试：

```bash
pnpm dev:host
# http://<本机内网IP>:5173
```

树莓派部署/预览：

```bash
scripts/deploy-web-pi.sh --mode preview --host 0.0.0.0 --port 4173
```

Runner 骨架可用以下方式启动；它当前只维护进程生命周期，尚未连接真实 LTX 管线：

```bash
ONEIROI_RUNNER_NAME=fast-0 \
ONEIROI_RUNNER_QUEUE=fast \
ONEIROI_RUNNER_GPU_DEVICE=0 \
uv run oneiroi-runner
```

## 4. 检查

```bash
pnpm check
uv run ruff check .
uv run pytest
pnpm --filter @oneiroi/web e2e
```

## 5. 后续实现顺序

1. Gateway 数据库模型、Redis 队列和任务状态迁移；
2. 单个 Fast Runner 的真实 I2V 适配器与心跳；
3. BFF 显式上传、SSE 和授权下载路由；
4. WebUI 接入真实 API；
5. 复制四个固定 GPU Runner，并补取消、超时、OOM 和审计。
