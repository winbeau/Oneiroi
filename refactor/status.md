# Oneiroi 当前状态

## 决策

保留 Oneiroi 独立产品：React/Pi BFF、即梦式首页、Agent、conversation、素材库和产品任务历史。GPU inventory、lease、Runner supervisor 和 LTX execution 逐步迁到 `gpu-server`。

## 2026-08-01 生产发布

- runtime release SHA：`fa7c28cc98edf423e2be8762ad13b55f606389eb`；Pi `/home/winbeau/oneiroi-studio` 与 H100 `/root/wenbiao_zhao/Oneiroi` 均运行该 SHA且工作区干净。
- `origin/main` 后续已有 `d88ae28912f08d78fa1ca78d27f132abd9d1201f` gpu-server canary adapter；它不属于本次已激活 runtime，未被自动部署。
- `video.icthub.top/*` 已加入现有 Cloudflare Access 应用，复用 Authentik OIDC/group policy；未登录 `/` 与 `/create` 均 302 到 Access team domain，audience 与应用一致，深链接 path/query 保留。
- Pi `oneiroi-bff.service` 与 immutable `oneiroi-web.service` active/running；公网 Tunnel 指向 `127.0.0.1:4173`，BFF 监听 `127.0.0.1:8000`。
- H100 `oneiroi-gateway` 与 `oneiroi-bff` 由 Supervisor 管理并健康；Gateway 监听 `127.0.0.1:18010`，BFF 监听 `10.30.176.95:18000`。
- Cloudflare Access JWT、稳定 `(issuer, subject) -> owner`、RSA 服务断言、mutation Origin CSRF、请求体上限和 Range 流式转发已激活。
- 固定 `lan-preview` 身份注入已删除；无 JWT、伪造 cookie/header、无服务断言的私有 API 请求均为 401。
- 双 owner 实机后端隔离通过：conversation 交叉读取 404、列表互不可见；资产 upload 201、Range 206、交叉读取 404、cleanup 204。
- 畸形 PNG 已从 500 修复为 422 `INVALID_IMAGE`，并增加回归测试。
- 发布质量门通过：Ruff、68 passed/5 skipped、前端 lint/typecheck/build、OpenAPI 一致性、部署脚本与 static server syntax。

## 仍待完成

1. 使用两个真实 Authentik 邀请账号完成浏览器端 group 拒绝、owner 稳定性、conversation/asset/job/SSE 隔离验收；当前不会把双 owner 服务断言测试冒充真实用户通过。
2. 在维护窗执行 Pi 整机 reboot，确认 user linger 下 BFF、Web、Tunnel 自动恢复；当前仅完成 enabled unit 与受控 restart 验证。
3. 确认 `video-in` 无内网依赖后停用剩余 LAN `oneiroi-studio.service`；公网 loopback Vite preview 已停止。
4. H100 当前没有 Oneiroi Runner/LTX inference 进程；真实生成继续等待 gpu-server Runner，不扩展 Oneiroi 自有 scheduler。

完整证据、release SHA 和回滚方法见 [`production-launch.md`](./production-launch.md)，执行 Agent 从 [`START_PROMPT.md`](./START_PROMPT.md) 启动。
