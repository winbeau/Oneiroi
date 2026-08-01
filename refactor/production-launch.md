# Oneiroi React 优先上线与三仓联调计划

> 首次探查与生产激活时间：2026-08-01。目标：`pi5`、`h100-server`。

## 0. 2026-08-01 生产发布记录

### 发布结论

- 生产 runtime release SHA：`fa7c28cc98edf423e2be8762ad13b55f606389eb`；Pi 与 H100 checkout 均固定并运行该 SHA，工作区干净。
- 发布后 `origin/main` 另有 `d88ae28912f08d78fa1ca78d27f132abd9d1201f` gpu-server canary adapter 提交；本次没有自动拉取或激活该后续功能，生产仍按上述 runtime SHA 冻结。
- Cloudflare Access 已保护 `video.icthub.top/*`，issuer 为 `https://restless-cherry-c802.cloudflareaccess.com`，application audience 为 `a9c5fe880b298db5a308ab2694ae0c6d2f1c165164075c91eb32191023be09c9`。
- 未登录请求 `/` 与 `/create?from=access-check` 均返回 302 到 Cloudflare Access；深链接 path/query 保留，没有 Bypass 证据。
- Pi 已运行 `oneiroi-bff.service` 和 immutable `oneiroi-web.service`：BFF 监听 `127.0.0.1:8000`，React origin 监听 `127.0.0.1:4173`，Tunnel 保持指向 loopback 4173。
- H100 Gateway/BFF 已由 Supervisor 管理：Gateway `127.0.0.1:18010`，BFF `10.30.176.95:18000`；两者 health 200。
- Pi 持有 3072-bit RSA 服务私钥，H100 只持有公钥；服务断言有效期为 300 秒，并仅容忍 120 秒有界时钟偏差。
- 发布验收发现畸形 PNG 触发 500；`fa7c28c` 已将 Pillow `SyntaxError` 映射为 422 `INVALID_IMAGE` 并增加回归测试。

### 验收证据

- 本地质量门：`uv run ruff check .`、`uv run pytest`（68 passed, 5 skipped）、`pnpm check`、`pnpm check:api`、部署脚本 shell syntax 和 static origin Node syntax 全部通过。
- Pi production origin：`/`、`/create?from=release`、`/healthz` 为 200；无 Access JWT、伪造 `oneiroi_user` cookie 或 `X-Oneiroi-User` 的 API 请求为 401。
- H100 私有边界：无服务断言访问 BFF/Gateway 为 401；有效 Pi 服务断言通过 H100 BFF 到 Gateway 为 200。
- 两个稳定映射测试 owner 的实机隔离：conversation 自读 200、交叉读取双向 404、列表互不可见；测试记录已精确清理。
- 资产实机验收：有效 PNG upload 201、10-byte Range 返回 206 与正确 `Content-Range`、另一 owner 读取 404、删除 204；畸形 PNG 返回 422 `INVALID_IMAGE`。
- Pi 已执行一次整机 reboot，`linger=yes` 下 BFF、Web 与 Tunnel 均自动启动。重启暴露出旧 LAN preview 重建共享 `dist` 的短暂 502 竞态；已移除 Tunnel 对旧 unit 的依赖，并彻底删除 LAN/loopback 两个旧 user units 及 `lan-preview`/`video-in` drop-ins。
- 清理后旧 units 均为 `LoadState=not-found`，只剩 `127.0.0.1:8000` 与 `127.0.0.1:4173` listener；Web `/`、深链接、health 为 200，伪造身份 API 为 401，公网 Access challenge 仍为 302。

### 尚未声称完成的门

- 尚无两个真实 Authentik 邀请用户的浏览器会话，因此真实用户登录后的 conversation/asset/job 隔离、group 拒绝与完整 SSE 流仍需人工双账号验收；当前证据覆盖 Access challenge、JWT/服务身份单测和双 owner 实机后端隔离，不伪造真实用户通过。
- 用户明确日常不依赖重启恢复，本次不再执行第二次 reboot；旧 units 已实时删除并验证依赖图，但不声称完成删除后的第二次冷启动复验。
- H100 当前没有 Oneiroi Runner/LTX inference 进程；生成任务必须真实失败或显示不可用，不能把 capability 声明当作生成链路成功。

### 回滚方法

- Access 策略始终保持启用；不得恢复固定 `lan-preview` 身份。若身份链路异常，先停止 `cloudflared-video.service`，再处理 runtime 回滚。
- 最近安全版本回滚点为 `5e68ebf6c5ca170df8be7c72b0866cfc37a3c675`。Pi 回滚：在 `/home/winbeau/oneiroi-studio` checkout 该 SHA、运行 frozen dependency sync、同步 `/home/winbeau/.config/oneiroi/web.env` 的 release SHA，然后重启 `oneiroi-bff.service` 与 `oneiroi-web.service`。
- H100 回滚：在 `/root/wenbiao_zhao/Oneiroi` checkout `5e68ebf6c5ca170df8be7c72b0866cfc37a3c675`、运行 `uv sync --all-packages --frozen`，再由 Supervisor 重启 `oneiroi-gateway` 与 `oneiroi-bff`。
- 仅在 public ingress 已关闭时，才可回到探查基线 Pi `18935366644f25cd88224798208793ef68bbb317` / H100 `69a53842db90bb43d6785611d385dbd66e5fe028`；不得删除数据库、storage、模型、temp 或密钥文件。

## 1. 第一目标

最优先把 Oneiroi React 以可登录、可区分用户、可回滚的方式上线 `video.icthub.top`，再接通 gpu-server 的真实 LTX 视频生成。

保留：

- 即梦式首页和灵感页；
- Agent 模式；
- conversation；
- 素材库；
- 产品任务历史；
- React/TanStack Query/Zustand；
- Pi BFF 产品边界。

不再继续扩展 Oneiroi 自有 GPU lease/Runner；新增算力功能统一进入 `gpu-server`。

## 2. 实机现状

### Pi 5

- checkout：`/home/winbeau/oneiroi-studio`；runtime SHA：`fa7c28cc98edf423e2be8762ad13b55f606389eb`；工作区干净。
- `oneiroi-bff.service`：active/running，监听 `127.0.0.1:8000`，验证 Cloudflare Access JWT 并签发 Pi→H100 服务断言。
- `oneiroi-web.service`：active/running，immutable `apps/web/dist`，监听 `127.0.0.1:4173`，`/healthz` 与深链接 fallback 正常。
- `cloudflared-video.service`：active/running，`video.icthub.top -> 127.0.0.1:4173`；仅依赖 `oneiroi-web.service`，未登录访问由 Access 在 origin 前挑战。
- `oneiroi-studio.service` 与 `oneiroi-studio-loopback.service` 已禁用并彻底删除，均为 `LoadState=not-found`；固定 `lan-preview` 与 `video-in` drop-ins 不再存在。
- 当前仅监听 `127.0.0.1:8000` 和 `127.0.0.1:4173`，没有 LAN 4173 或 canary 4174 listener。
- user linger 已开启，`oneiroi-bff.service`、`oneiroi-web.service` 与 Tunnel 已在一次实机 reboot 后自动恢复；用户要求不再做第二次 reboot。

### H100 server

- checkout：`/root/wenbiao_zhao/Oneiroi`；runtime SHA：`fa7c28cc98edf423e2be8762ad13b55f606389eb`；工作区干净。
- `oneiroi-gateway`：Supervisor RUNNING，`127.0.0.1:18010`，health 200，无服务断言的私有 API 为 401。
- `oneiroi-bff`：Supervisor RUNNING，`10.30.176.95:18000`，health 200，伪造 cookie/header 为 401。
- Gateway/BFF 的受限环境存放在 `/root/wenbiao_zhao/oneiroi-config/*.json`，不进入 Git；服务公钥文件 fingerprint 已在 Pi/H100 两端核对一致。
- Redis/PostgreSQL 与既有持久化数据保持不变；发布未删除 storage、temp、模型或数据库数据。
- 当前仍未发现 Oneiroi Runner/worker_process/LTX inference 进程；真实生成由后续 gpu-server 接入阶段完成。

## 3. 当前最高风险

### 已关闭：固定身份与公开绕过

Vite 不再注入 `ONEIROI_API_PROXY_USER`，生产 BFF 不信任浏览器 cookie/header；`video.icthub.top/*` 已由 Cloudflare Access 保护，未登录请求不再直达 React origin。

### 待人工：真实 Authentik 双账号与 group policy

已验证 Access challenge/audience/深链接回跳、JWT 单测和双 owner 后端隔离；仍需两个真实邀请账号验证 Authentik group 拒绝、登录后 owner 稳定性以及 conversation/asset/job/SSE 的浏览器端互不可见。

### 已修复：Pi 开机 preview 竞态

首次 reboot 时，历史 `cloudflared-video.service` 依赖拉起旧 LAN preview，后者重建共享 `dist` 并造成短暂 502。Tunnel 现只依赖 immutable Web，旧 preview units/drop-ins 已彻底删除；用户要求不再安排第二次 reboot。

### 存储运行约束

H100 探查时文件系统显示 100% 但仍约 9.5 GiB 可用；禁止重新下载/复制权重，attempt temp 必须及时清理并设置低水位 admission。

### 已关闭：LAN preview 与固定身份残留

LAN/loopback preview units、`ONEIROI_API_PROXY_USER=lan-preview` 和 `video-in` host drop-in 已删除；systemd user 目录中没有相关残留，LAN 4173 listener 已消失。

### P1：Runner 不在线

capability available 只证明资产/配置判断通过，不证明当前存在可执行 worker。真实 LTX Fast E2E 必须等待 gpu-server Runner。

## 4. 前端视觉基线

Oneiroi 已接近 `xju-feiyue` 的 warm-neutral 风格，但上线前统一以下 token：

- 背景：`#ffffff`、`#f7f6f3`、hover `#f1f1ef`；
- 主文字 `#37352f`，弱文字 `#787774`，边框 `#edece9`；
- 圆角以 6/8/12px 为基础；大视频预览可保留产品级 14/18px，但需有明确语义；
- UI 字体 `Inter Tight/PingFang SC`；展示标题优先 `Source Serif 4/Noto Serif SC`；
- 普通卡片使用浅边框和 `0 1px 2px rgba(0,0,0,.04)`，不使用大面积重阴影；
- 150ms 微交互，200–320ms layout，选择性 560–600ms hero/reveal；
- 所有 Motion 组件必须服从 `prefers-reduced-motion`；
- 紫色只作为 Oneiroi Agent/生成状态的产品强调色，不能替代基础中性色。

## 5. 上线阶段

### O-L0：冻结并记录运行基线（半天）

1. 记录 Pi/H100 checkout、unit、进程、端口、Tunnel 和当前回滚命令。
2. 选择一个 runtime release SHA；Pi/H100 只更新到该 SHA。
3. 运行前端 lint/typecheck/build、后端 Ruff/pytest。
4. 后端 CI 若缺 FFmpeg，应显式处理 CI prerequisite；不要把生产失败伪装为 skip。
5. 保留当前 user units 和 H100 uvicorn 启动命令作为回滚。

完成门：两端 release SHA 和 OpenAPI contract 一致。

### O-L1：先完成用户登录边界（1–2 天）

1. 为 `video.icthub.top/*` 建立与 ComfyUI 同级的 Cloudflare Access app。
2. 共用 Authentik generic OIDC login method 和 group policy；禁止 Bypass。
3. 验证 `/`、`/create`、conversation 深链接登录后回到原 path/query。
4. BFF 验证 `Cf-Access-Jwt-Assertion` 的 signature、issuer、audience、expiry。
5. 将 `(issuer, subject)` 映射为稳定内部 owner ID。
6. 删除 Vite proxy 的固定 `oneiroi_user=lan-preview` 注入。
7. BFF→H100 Gateway/gpu-server 使用服务身份，与浏览器用户分离。

完成门：两个邀请码用户创建的 conversation/asset/job 相互不可见；伪造 cookie/header 无效。

### O-L2：React 安全 beta 上线（1 天）

最短路径先保留现有 loopback Vite preview，但明确标记临时：

- Tunnel 只指向 `127.0.0.1:4173`；
- 移除不需要的 LAN preview/`video-in` 兼容路径前先确认没有内网依赖；
- systemd user unit 固定 release SHA，部署脚本不在启动时隐式 pull；
- 构建产物和运行日志可追溯；
- health、API proxy、SSE、upload 和 Range 下载均通过 Access。

随后生产化：immutable `dist/`、静态服务、loopback BFF、system-level service 或受控 user service。Pi 当前没有 Caddy；若实施需要系统安装，Agent 必须停止并给出一条完整 sudo 安装命令，不得自行安装或下载二进制。

完成门：Pi reboot 后自动恢复；公开页面不依赖开发服务器/HMR；回滚可在 5 分钟内执行。

### O-L3：产品体验收口（1–2 天）

- 首页、灵感流、创建页、素材库、conversation 和任务历史空/错/加载状态完整；
- Agent 模式是可执行参数编排，不只是动画面板；
- 新用户首次进入有模板和明确输入引导；
- compute 不可用时不伪造成功，显示真实原因；
- SSE reconnect 使用 snapshot 恢复；
- MP4 下载/播放支持 Range，不全量缓冲 Pi 内存；
- xju-feiyue 视觉 token 和可访问性验收。

### O-L4：接入 gpu-server（3–7 天，与 gpu-server 并行）

1. 保留 route/service ports，新增 `HttpGpuServerComputeBackend` 和 `HttpGpuServerJobExecutor`。
2. Oneiroi 继续拥有 product job、conversation、asset ownership 和产品 SSE。
3. gpu-server 拥有 lease、reservation、attempt、Runner、LTX 和 execution artifact。
4. 先 shadow capability/inventory，再 Fast canary，再 Fast/HQ 全切换。
5. 输入输出改 artifact ID/stream/URL，不传服务器路径。
6. 旧 Gateway/Runner 完成已有任务后 drain，禁止同一 idempotency key 双执行。

### O-L5：真实邀请用户 E2E（1–2 天）

完整链路：

```text
邀请码注册
  -> 邮箱验证
  -> video.icthub.top Access
  -> Authentik 登录/可选 TOTP
  -> Oneiroi unique owner
  -> Agent prompt + image
  -> gpu-server lease/reservation
  -> H100 LTX Fast
  -> artifact
  -> Oneiroi history/SSE/video Range
```

至少验证：成功、取消、H100 无卡、VPN 短断、页面刷新、Pi reboot、重复提交和越权读取。

## 6. 暂不做

- 本阶段不 transfer Oneiroi 仓库，先完成上线和身份边界。
- 不在 Oneiroi 新写另一套 GPU scheduler。
- 不在浏览器保存服务 token。
- 不因磁盘满自动删除 H100 文件。
- 不把 Vite preview 直接称为最终生产部署。

## 7. 时间估算

- 登录安全 beta：约 2–3 天。
- React 产品上线收口：约 1–2 天。
- gpu-server Fast 真机 E2E：约 3–7 天；当前空间即可开始，主要依赖 Runner/artifact 实现。
- 三仓邀请用户联调：约 1–2 天。

总计约 1–2 周，H100 存储处理、Cloudflare Access 手工配置和 LTX 运行稳定性带来约 ±40% 不确定性。
