# Oneiroi 当前状态

## 它不是空仓库

Oneiroi 已经是完整的视频生成产品 monorepo，而不只是“Agent 计划”：

- React 19/Vite 前端；
- Pi FastAPI BFF；
- GPU Gateway；
- PostgreSQL、Redis lease/streams；
- GPU session/slot/job 状态机；
- per-GPU Runner supervisor；
- LTX-2.3 Fast/HQ adapters；
- SSE、取消、上传、artifact、migration 和测试。

## 当前主要问题

1. `oneiroi_user` cookie 只是可伪造字符串，生产身份未完成。
2. BFF→Gateway 没有强服务认证。
3. Gateway/Runner 依赖 Redis 和共享本地文件路径。
4. 现有调度能力与新 `gpu-server` 高度重复。
5. Pi 下载 MP4 会全量缓冲到内存。
6. Pi 生产 systemd/Caddy/cloudflared 部署未完整落地。
7. 当前 GitHub CI 有 3 个既有后端 workflow/recovery 测试失败。

## 两条可选路线

### 保留 Oneiroi 产品

适合仍然需要即梦式首页、conversation、素材库、Agent 提示词、任务历史和专用视频体验。保留 React/FastAPI 产品层，但把 GPU lease/Runner/LTX 调度迁到 `gpu-server`。

### 并入 ComfyUI

适合优先减少维护：用 ComfyUI workflow、模板和 remote LTX custom node 替代 Oneiroi 产品。可以让 `video.icthub.top` 跳转或代理到一个预配置视频工作区，然后归档 Oneiroi。

代价是失去即梦式产品首页、专用素材/对话模型和独立 Agent UX。

## 建议

如果目标是“尽量不自建产品”，建议先用 ComfyUI + LTX workflow 验证视频生成主链路，再决定是否保留 Oneiroi。不要同时维护 Oneiroi 自带调度器和独立 gpu-server。
