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
- H100 文件系统只剩约 9.5 GiB，是实际生成硬阻塞。
- Pi/H100 runtime commit 不一致，需要固定同一 release。

## 当前 P0

1. `video.icthub.top/*` 加入与 ComfyUI 同级的 Cloudflare Access + Authentik OIDC。
2. BFF 验证 Access JWT，删除固定用户 cookie。
3. 把 React 从“页面可打开”推进到可回滚、可重启、可区分用户的安全 beta。
4. 处理 H100 存储后再启动 gpu-server Runner/LTX 真机生成。

完整计划见 [`production-launch.md`](./production-launch.md)，执行 Agent 从 [`START_PROMPT.md`](./START_PROMPT.md) 启动。
