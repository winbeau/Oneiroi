# 仓库架构

## 部署边界

```text
Browser
  └─ HTTPS → Caddy (Raspberry Pi)
               ├─ static files → apps/web build
               └─ /v1/* → apps/bff
                              └─ Cisco VPN/private route → services/gateway (H100)
                                                                  ├─ PostgreSQL
                                                                  ├─ Redis queues
                                                                  ├─ controlled storage
                                                                  └─ workers/runner × 4
```

- `apps/web`：Vite 构建的 React SPA。使用 React Router、TanStack Query、Zustand 和 Tailwind CSS。它不持有 H100 地址或凭据。
- `apps/bff`：Pi 上的薄 BFF，负责同源 API、入口身份上下文、上传预检、授权下载转发和受控错误映射。禁止实现任意目标反向代理。
- `services/gateway`：H100 私网中的应用协调层，后续承载会话、资产、任务、SSE、数据库与队列逻辑。
- `workers/runner`：每个进程固定一个 GPU 和一个队列。计划部署 `fast-0/GPU 0`、`fast-1/GPU 1`、`hq-0/GPU 2`、`hq-1/GPU 3`。
- `packages/python/common`：跨 Python 服务共享的稳定契约；不要在此放数据库访问或部署专属配置。

## 与开题计划的适配

开题计划原选型使用 Next.js 承担 WebUI/BFF。当前仓库按开工要求改为 pnpm + Vite，因此将职责拆为：

1. Vite 只构建前端静态资源；
2. 独立 FastAPI BFF 提供同源 `/v1` API；
3. Caddy 在生产环境统一静态资源与 BFF 的 Origin。

这样保留了“浏览器只看见 Pi 入口、H100 Gateway 不暴露”的安全边界。

## API 与任务边界

一期 API 统一使用 `/v1` 前缀。计划中的资产、会话、I2V 任务、SSE、取消和授权下载端点将在 BFF 与 Gateway 中按显式路由逐项实现。

共享任务状态机定义在 `oneiroi_common.jobs.JobStatus`：

```text
draft → uploaded → queued → assigned → preparing → generating → encoding → succeeded
任一非终态 → cancelled | failed
```

队列只允许 `fast` 和 `hq`。浏览器传入的文件路径、队列名和用户标识都不能直接成为服务端可信值。

## 目录约束

- 前端业务按 `features/` 组织，跨页面组件放 `components/`，外部访问封装在 `lib/`。
- Python 服务采用 `src/` layout，避免从仓库工作目录意外导入未安装代码。
- 基础设施模板不得包含真实域名凭据、Tunnel token、账户信息、私网地址或生产密码。
- 模型、上传和结果文件不提交 Git；本地状态放 `.data/`。
