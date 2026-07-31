# Oneiroi Studio

面向内部用户的私有图生视频创作平台。仓库当前提供按部署边界拆分的 MVP 基础架构，产品与技术范围见 [`Oneiroi-Studio-开题计划.md`](./Oneiroi-Studio-%E5%BC%80%E9%A2%98%E8%AE%A1%E5%88%92.md)。

## 仓库结构

```text
apps/
  web/                  Vite + React + TypeScript WebUI
  bff/                  部署在入口机上的 FastAPI 同源 BFF
services/
  gateway/              部署在 H100 私网的 FastAPI Gateway
workers/
  runner/               固定 GPU、固定队列的推理 Runner
packages/python/common/ Python 公共契约与枚举
infra/
  caddy/                双域名 Web 入口模板
  cloudflared/          Cloudflare Tunnel 配置模板
docs/                   架构与本地开发说明
```

前端由 **pnpm + Vite** 管理；后端是 **uv workspace**。浏览器只访问 Web 入口的同源 `/v1` API，BFF 再通过实验室私网访问 Gateway。Runner、Redis 和 PostgreSQL 不向浏览器或公网暴露。

## 快速开始

要求：Node.js 22+、pnpm 10+、Python 3.12、uv、Docker（可选，本地 Redis/PostgreSQL）。

```bash
cp .env.example .env
pnpm install
uv sync --all-packages

docker compose up -d postgres redis       # 可选
uv run uvicorn oneiroi_gateway.main:app --reload --port 8010
uv run uvicorn oneiroi_bff.main:app --reload --port 8000
pnpm dev
```

Vite 开发服务器位于 `http://localhost:5173`，并将 `/v1` 与 `/healthz` 代理到 BFF。BFF 未启动时，前端自动使用浏览器演示任务流。

工作区内网访问：

```bash
pnpm dev:host
# http://<本机内网IP>:5173
```

树莓派构建并监听所有接口：

```bash
scripts/deploy-web-pi.sh --mode preview --host 0.0.0.0 --port 4173
```

前端复刻与部署方案见 [`docs/frontend-replication-plan.md`](./docs/frontend-replication-plan.md)。

## 质量检查

```bash
pnpm check
uv run ruff check .
uv run pytest
```

更多说明见 [`docs/development.md`](./docs/development.md) 和 [`docs/architecture.md`](./docs/architecture.md)。
