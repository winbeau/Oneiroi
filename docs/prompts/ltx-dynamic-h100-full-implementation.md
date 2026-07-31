# 新对话执行提示词：完整实现 LTX-2.3 动态 H100 工作流

你是 Oneiroi Studio 项目的主开发代理。请在当前仓库中把 LTX-2.3 动态 H100 方案从现有骨架完整实施到可验证状态，不要只停留在设计、P0 或模拟流程。

## 1. 工作目录与事实来源

本地仓库：

```text
/home/winbeau/Projects/Oneiroi
```

远程仓库：

```text
https://github.com/winbeau/Oneiroi.git
```

开始前检查：

```bash
git status --short
git branch --show-current
git log -1 --oneline
```

不要假设提示词中的 commit 一定是最新状态。仓库当前代码、Git 历史、测试和运行环境才是事实源。

必须完整读取并遵循：

- @docs/ltx-desktop-inspired-backend-plan.md
- @docs/ltx-backend-plan/01-reference-and-baseline.md
- @docs/ltx-backend-plan/02-backend-architecture.md
- @docs/ltx-backend-plan/03-gpu-resource-lifecycle.md
- @docs/ltx-backend-plan/04-job-api-and-persistence.md
- @docs/ltx-backend-plan/05-frontend-compatibility.md
- @docs/ltx-backend-plan/06-implementation-and-validation.md
- @docs/ltx-backend-plan/07-private-api-validation.md
- @docs/architecture.md
- @docs/development.md
- @docs/ltx-2.3-h100-inference-plan.md

同时检查现有实现和测试，不得覆盖已有正确能力：

- @packages/python/common/src/oneiroi_common
- @services/gateway/src/oneiroi_gateway
- @workers/runner/src/oneiroi_runner
- @apps/bff/src/oneiroi_bff
- @apps/web/src
- @apps/bff/tests
- @services/gateway/tests
- @apps/web/e2e
- @scripts/run-ltx-2.3.sh
- @scripts/compare-ltx-2.3-quality.sh
- @compose.yaml

## 2. 总任务

按主计划 P0 → P7、M1 → M8 顺序完成全部实现：

1. 类型化 Compute/GPU/Runner/Job 契约；
2. NVML inventory、heartbeat 和动态空闲卡判定；
3. 单卡 Fast Supervisor/Model Worker 热加载、生成和释放；
4. 1–4 卡 Redis 租约、自动/手动分配和资源会话；
5. HQ profile、完整 PipelineSpec 和 1 卡禁用 HQ；
6. PostgreSQL 持久任务、Redis 定向任务流、SSE、取消、重试、上传和真实 MP4；
7. Pi BFF 薄代理、可信身份上下文和授权下载；
8. Web ComputeControl、GPU 选择、逐卡状态、真实任务 Timeline 和释放交互；
9. 关闭生产环境静默模拟成功；
10. 故障恢复、容量测试和显存回收验证；
11. 在不暴露公网的条件下完成 GET、POST、PUT 和真实 Compute session 测试。

不要在完成某一个里程碑后自动结束。每个里程碑验收通过后提交一次 Git，然后继续下一个里程碑，直到 P7 完成或触发明确停止条件。

## 3. 实施纪律

### 3.1 先建立进度事实

开始实现时创建或更新：

```text
docs/ltx-backend-plan/implementation-progress.md
```

只记录可验证事实：

- 当前阶段和里程碑；
- 已完成文件；
- 已执行检查；
- H100 验证结果；
- 未解决阻塞；
- 对应 commit。

不得仅根据日志文字或代码存在就标记完成，必须满足对应验收条件。

### 3.2 分阶段提交

建议提交边界：

```text
M1: compute contracts and GPU inventory
M2: single-GPU Fast worker lifecycle
M3: dynamic GPU session scheduling
M4: HQ profile lifecycle
M5: persistent jobs and real assets
M6: frontend compute workflow
M7: reliability and production hardening
M8: private API validation
```

每次提交前：

- 审查 `git diff`；
- 运行该阶段相关测试；
- 运行 `git diff --check`；
- 确认模型、上传、视频、token、agent 状态和本地参考仓库未进入 Git；
- 更新进度文档；
- 提交并推送。

### 3.3 不进行无依据的大重写

优先扩展现有 Vite、React、FastAPI、Zustand、TanStack Query、PostgreSQL、Redis 和 Python workspace。不要引入新的前端框架或另建重复服务。

路由保持薄层，重型逻辑进入 service/adapter/repository。真实 Torch/LTX 只允许出现在 Model Worker，不允许 Gateway 或 BFF 导入。

## 4. 跨阶段强制要求

### GPU 和资源

- 默认请求 4 张 GPU；
- 最大实际分配 4 张；
- 实际分配为 `min(requested, eligible, 4)`；
- 不写死 GPU 0–3；
- 使用 GPU UUID 做稳定标识和租约键；
- 物理 index 只用于展示；
- 不以 P-state 判断空闲；
- 不抢占、终止或干扰外部 CUDA 进程；
- 1 卡只加载 Fast，HQ 由后端硬性禁用；
- 2 卡为 1 Fast + 1 HQ；
- 3 卡为 2 Fast + 1 HQ；
- 4 卡为 2 Fast + 2 HQ；
- HQ 加载失败不得静默降级为 Fast；
- 一个 ready slot 同时最多运行一个任务。

### 热加载和释放

- 服务启动时不自动占用显存；
- 用户显式创建 Compute session 后才加载模型；
- Model Worker 一个生命周期只驻留一个完整 PipelineSpec；
- ready 必须在 checkpoint、权重迁移、必要组件初始化和 warm-up 完成后发布；
- release 默认 `when_idle`；
- 强制取消运行任务必须二次确认；
- 释放最终通过退出 Model Worker 子进程销毁 CUDA context；
- 释放成功必须同时满足子进程退出、Redis 租约清除和 NVML 显存回落；
- 测试结束后必须释放本次申请的 GPU。

### 任务和存储

- PostgreSQL 是 job、attempt、event、session、slot 和 asset 的事实源；
- Redis 只用于租约、定向控制流、任务流、心跳和实时通知；
- Gateway 先选择 ready slot，再写入该 slot 的 Redis Stream；
- 保留 `/v1/jobs/i2v` 和现有 SSE 路径；
- 支持 queued、assigned、loading_model、preparing、generating、encoding 和 terminal 状态；
- 区分 `cancel_requested` 与 `cancelled`；
- 重试创建新的 attempt，不覆盖历史错误和日志；
- 上传使用 multipart/asset ID，不接受任意服务器路径；
- 成功结果必须是真实 MP4 和独立 manifest，不得用 JSON 或图片预览伪装视频。

### 前端

- 继续使用现有 React/Vite/TypeScript/Tailwind/Zustand/TanStack Query；
- 增加 ComputeControl、GPU selector、逐卡热加载进度和释放确认；
- Fast/HQ、分辨率和时长由后端 capabilities 驱动；
- 无 ready session 时禁止真实提交；
- 1 卡时禁用 HQ 并展示后端原因；
- JobTimeline 使用后端 SSE，不由浏览器 timer 推进生产任务；
- production 关闭静默 browser simulation fallback；
- Demo 模式只能由显式环境变量开启，并清楚标识为 Demo；
- Agent 建议保持可编辑，必须由用户显式确认后才能提交长任务。

## 5. PUT API 要求

实现幂等资源更新：

```http
PUT /v1/conversations/{conversation_id}
```

请求：

```json
{
  "title": "更新后的创作会话"
}
```

同时保证：

- `POST /v1/conversations` 创建会话；
- `GET /v1/conversations` 列表；
- `GET /v1/conversations/{id}` 详情；
- PUT 重复提交不会创建重复资源；
- PUT 不允许客户端创建任意 ID；
- 不存在或非 owner 返回 404；
- 非法 title 返回 422；
- Conversation canonical state 位于 Gateway，BFF 只代理。

不要为了满足 PUT 测试而错误地把任务提交、cancel 或 release 改成 PUT。

## 6. 远程环境

可信 SSH 目标：

```text
H100: h100-server
Pi:   pi5
```

H100 模型和源码基线位于：

```text
/data/oneiroi/ltx-2.3
```

历史上曾观察到 GPU 0、1、2、7 空闲、3–6 被占用，但这只是历史快照。每次测试必须重新读取实时 NVML inventory。

远程工作要求：

- 复用同一目标上的 tmux terminal；
- 不请求或保存密码、SSH key、token；
- 禁止 sudo、su、doas、pkexec 或身份切换；
- 如果必须 sudo，立即停止并只报告所需命令；
- 不终止其他用户进程；
- 不修改 GPU compute mode；
- 不使用固定 index 绕过调度器；
- 首次真实热加载只使用 1 张 eligible GPU；
- 单卡验证通过后再按实时空闲数量扩展到最多 4 张。

## 7. 不暴露公网的测试要求

最终 P7/M8 必须完整执行 @docs/ltx-backend-plan/07-private-api-validation.md。

### 7.1 网络边界

测试期间禁止：

- 新建或修改 Cloudflare Tunnel ingress；
- 修改公网 DNS；
- 修改路由器端口转发；
- 将 Gateway/BFF 测试端口绑定到 `0.0.0.0` 或 `[::]`；
- 使用 `https://video.icthub.top` 测试新 API；
- 将临时 API 接入现有公网入口。

优先使用：

```text
ASGI TestClient
http://127.0.0.1:<temporary-port>
SSH 目标主机内 curl --noproxy '*'
```

临时 HTTP 服务建议：

```text
Gateway: 127.0.0.1:18010
BFF:     127.0.0.1:18000
```

如果端口被占用，动态选择其他 loopback 端口并记录。

### 7.2 必测方法链

非 GPU 破坏性测试：

1. GET `/healthz`；
2. GET `/v1/compute/capabilities`；
3. POST `/v1/conversations`；
4. PUT `/v1/conversations/{id}`；
5. 重复相同 PUT 验证幂等；
6. GET `/v1/conversations/{id}`；
7. GET `/v1/conversations`；
8. 验证 owner 隔离、404 和 422。

真实 Compute 测试：

1. GET `/v1/compute/gpus`；
2. POST `/v1/compute/sessions`，先请求 1 卡；
3. GET session snapshot 和 SSE；
4. 验证 1 卡 HQ 禁用；
5. 提交最小 Fast I2V job；
6. GET job/SSE，等待真实 terminal state；
7. 下载并验证真实 MP4；
8. POST release；
9. 验证子进程、租约和显存释放。

使用 `jq -e` 或 Python 对响应做字段断言，不能只看 HTTP 200。

### 7.3 监听检查

测试服务启动后和结束前检查：

```bash
ss -ltnp
docker ps --format '{{.Names}}\t{{.Ports}}'
```

测试端口只能显示为 `127.0.0.1:<port>`。测试结束后关闭所有临时进程和端口。

## 8. 分阶段检查

每个 Python 阶段至少执行：

```bash
uv run ruff check .
uv run pytest
```

涉及前端时执行：

```bash
pnpm check
```

涉及浏览器流程时执行现有 Playwright E2E，并增加 ComputeControl、1 卡禁 HQ、热加载、释放和生产无模拟 fallback 用例。

每个阶段都执行：

```bash
git diff --check
```

真实 H100 测试要额外记录：

- 选中的 GPU UUID 和 physical index；
- 选卡前外部占用情况；
- profile 加载耗时；
- ready 后稳定显存；
- 任务峰值显存和各阶段耗时；
- release 后显存；
- 是否存在 orphan CUDA process。

日志中只显示截断 GPU UUID，不记录其他用户进程的完整命令行。

## 9. 停止条件

只在以下情况停止并报告：

1. 需要 sudo 或身份切换；
2. 需要密码、token、私钥或其他秘密；
3. 必须终止或抢占其他用户进程才能继续；
4. 真实 GPU 全部被外部任务占用，无法安全执行热加载；
5. 模型资产缺失或损坏且无法从现有可信路径恢复；
6. 出现可能损坏现有生成资产、数据库或 Git 历史的操作；
7. 文档要求发生不可调和冲突。

如果只是没有空闲 GPU：继续完成代码、fake/integration tests、前端和私网非 GPU HTTP 测试，只把真实热加载验证标记为 blocked，不得抢卡。

不要为可以通过读取仓库、测试或运行环境解决的问题询问用户。

## 10. 完成定义

全部任务只有在以下条件满足时完成：

- P0–P7、M1–M8 均有可验证结果；
- 动态 1–4 卡调度不依赖连续物理 index；
- 单卡 Fast 真实热加载、连续任务复用和释放通过；
- HQ profile 和 1 卡禁用策略通过；
- PostgreSQL/Redis 真实任务链通过；
- 前端完整使用真实 Compute/Job API；
- 生产模式不再静默模拟成功；
- GET、POST、PUT ASGI 测试通过；
- GET、POST、PUT loopback smoke test 通过；
- 最小真实 I2V 返回可播放 MP4；
- 测试没有新增任何公网入口；
- 所有临时服务关闭；
- 所有测试、lint、类型检查和适用 E2E 通过；
- 进度文档和模块计划反映真实状态；
- 每个里程碑已提交并推送；
- Pi 仅通过 Git 做版本同步，是否重启服务由实际前端部署需要决定。

## 11. 最终报告格式

最终只报告可验证事实：

1. P0–P7 完成表；
2. 后端、Runner、BFF、前端主要文件；
3. 数据库 migration 和 Redis stream/lease 设计；
4. Fast/HQ 实测加载与推理数据；
5. GET/POST/PUT 测试结果；
6. `ss`/Docker 监听检查结果；
7. 真实 MP4 路径、大小和媒体探测结果，不附二进制；
8. 测试和 E2E 结果；
9. 已知风险或真实阻塞；
10. 各里程碑 commit hash 和最终 commit；
11. 确认已释放本次 GPU、关闭临时服务且未增加公网入口。
