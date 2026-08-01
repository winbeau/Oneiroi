# Oneiroi 当前状态

## 决策

保留 Oneiroi 独立产品：React/Pi BFF、即梦式首页、Agent、conversation、素材库和产品任务历史。GPU inventory、lease、Runner supervisor 和 LTX execution 逐步迁到 `gpu-server`。

## 已有实现

- React 19/Vite/TanStack Query/Zustand；
- Pi BFF 与 H100 Gateway；
- PostgreSQL、Redis；
- GPU session/slot/job 状态机；
- Runner supervisor 与 LTX Fast/HQ adapters；
- SSE、取消、上传、artifact、migration 和测试；
- xju-feiyue 派生的 warm-neutral token、Motion/reduced-motion；
- Agent 面板、conversation、素材库和任务历史页面。

## 2026-08-01 实机状态

- Pi `/home/winbeau/oneiroi-studio` 已运行 React Vite preview 和 `video.icthub.top` Tunnel。
- Pi proxy 到 H100 BFF 的 health、conversation 和 8 GPU inventory 可用。
- 当前固定注入 `oneiroi_user=lan-preview`，不能开放多用户。
- 当前有两个 Vite preview 实例，尚非 immutable static production deployment。
- H100 BFF/Gateway、Redis/PostgreSQL 正常；没有 Runner 进程。
- H100 8 张 H100 中当前 4 张 eligible，Fast/HQ capability 声明可用。
- H100 当前约 9.5 GiB；权重已齐且单视频几 MiB，足够 Fast MVP，但必须禁止重复下载并及时清理 temp。
- Pi/H100 runtime commit 不一致，需要固定同一 release。

## 当前 P0

1. `video.icthub.top/*` 加入与 ComfyUI 同级的 Cloudflare Access + Authentik OIDC；当前未登录仍返回 200，远端策略尚未生效。
2. Access JWT、稳定 owner、RSA 服务断言、CSRF、Range 流式转发和固定用户 cookie 删除已在本地实现并通过测试，等待 Access application audience 后激活。
3. immutable React static origin 与 user unit 模板已完成，等待身份门通过后部署到 Pi 并执行 reboot 恢复验收。
4. 现有模型 preflight、temp cleanup/admission 和 gpu-server Runner/LTX Fast 真机生成保持后续阶段；不扩展 Oneiroi 自有 scheduler。

完整计划见 [`production-launch.md`](./production-launch.md)，执行 Agent 从 [`START_PROMPT.md`](./START_PROMPT.md) 启动。
