# Oneiroi 启动提示词

你正在 `/home/winbeau/Projects/Oneiroi` 工作。首要目标不是重写产品，而是把现有 React 视频 Agent 安全上线 `video.icthub.top`，并为接入 `xjuIcthub/gpu-server` 做好边界。

## 必须先读

- `refactor/production-launch.md`
- `refactor/plan.md`
- `refactor/status.md`
- `AGENTS.md`（若存在）
- `.github/workflows/ci.yml`
- `apps/web/package.json`
- `apps/web/vite.config.ts`
- `apps/web/src/styles.css`
- `scripts/deploy-web-pi.sh`
- `packages/python/common/src/oneiroi_common/{compute,generation,runner_protocol}.py`

## 已知实机事实（2026-08-01）

- Pi target：`pi5`，checkout `/home/winbeau/oneiroi-studio`，运行 commit `1893536`。
- Pi user services：`oneiroi-studio.service`、`oneiroi-studio-loopback.service`、`cloudflared-video.service`。
- 当前是 Vite preview，`video.icthub.top -> 127.0.0.1:4173`。
- 当前 proxy 固定注入 `oneiroi_user=lan-preview`，这是 P0 安全问题。
- Pi 可访问 H100 `10.30.176.95:18000`；health、conversation、8 卡 inventory 已通过。
- H100 Gateway `127.0.0.1:18010`，BFF `10.30.176.95:18000`；当前无 Runner 进程。
- H100 8×H100，当前 4 卡 eligible；文件系统只剩约 9.5 GiB，禁止启动真实产物任务或自动清理。
- 本仓库保留 React/BFF/conversation/assets/product history；GPU lease/Runner/LTX 最终由 gpu-server 拥有。

## 你的执行顺序

1. 先审计当前分支与 Pi/H100 release SHA，不直接部署不一致 commit。
2. 修复生产身份：`video.icthub.top/*` Cloudflare Access 与 ComfyUI 同级，共用 Authentik OIDC；BFF 验证 Access JWT；移除固定 `lan-preview` cookie。
3. 保持 route handler 薄，新增身份 adapter 和稳定 `(issuer, subject) -> owner` 映射；不要信任浏览器 header/cookie。
4. 先让 React 安全 beta 上线：单 loopback origin、可回滚 user/system service、health/API/SSE/upload/Range 全通过。
5. 对齐 `xju-feiyue` 风格：白/暖灰背景、`#37352f/#787774/#edece9`、6/8/12px、浅边框、Inter Tight/Source Serif、完整 reduced motion；紫色仅作 Oneiroi 强调色。
6. 完善 Agent 创建链路、conversation、素材库、任务历史和错误状态，不做纯演示假成功。
7. 为 `HttpGpuServerComputeBackend`/`HttpGpuServerJobExecutor` 写 contract tests，但不要在 Oneiroi 新建 GPU scheduler。
8. 运行前端 lint/typecheck/build、后端 Ruff/pytest；查明并处理 FFmpeg CI prerequisite，不隐藏失败。
9. 更新 `refactor/production-launch.md` 的完成状态、Pi/H100 release SHA、验收证据和回滚命令。

## 强制约束

- 不泄露或提交 Cloudflare、Authentik、SMTP、数据库、Hugging Face、Tunnel 或 service token。
- 不把 server-local paths 放入跨服务 DTO。
- 不把 `cancel_requested` 当 `cancelled`。
- 不在 H100 磁盘满时启动真实视频任务。
- 不用 Docker 新建 Oneiroi/gpu-server 部署。
- 不自动删除远端文件。
- 不自行执行 sudo。若缺 Caddy/系统依赖，停止并给出一条完整 sudo 安装命令。
- 远端相关工作复用 `pi5`/`h100-server` tmux terminal；只读确认后再部署。

## 完成标准

- 未登录访问 Oneiroi 深链接会进入 Authentik，登录后回原 path/query。
- 两个邀请用户的 conversation、asset、job 相互隔离。
- Studio 有 Oneiroi 同级入口。
- Pi reboot 后 React/BFF/Tunnel 恢复。
- React 不依赖固定用户 cookie；伪造身份无效。
- fake 或真实 gpu-server contract 跑通；真实生成只有在 H100 空间和 Runner 满足后执行。
- 工作区 clean，commit/push 完成，CI 通过；报告具体 run ID 和剩余阻塞。
