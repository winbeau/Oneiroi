# Oneiroi React 优先上线与三仓联调计划

> 探查时间：2026-08-01。远端只读探查目标：`pi5`、`h100-server`。

## 0. 2026-08-01 执行记录

### 已完成：身份与生产 origin 实现

- BFF 新增 Cloudflare Access JWT 的 RS256/JWKS、issuer、audience、expiry 验证；生产环境不再信任浏览器 `oneiroi_user` cookie 或 `X-Oneiroi-User`。
- `(issuer, subject)` 通过稳定 SHA-256 adapter 映射为内部 owner；conversation、asset、job 和 compute session 继续使用既有 owner 过滤。
- Pi BFF 使用本机 RSA 私钥签发 60 秒服务断言；H100 BFF 与 Gateway 使用公钥验证，并校验断言 subject 与内部 owner header 一致。
- mutation 增加同源 Origin CSRF 检查；下载转发支持 Range/If-Range/ETag/Content-Range 并采用流式响应。
- Vite 已删除 `ONEIROI_API_PROXY_USER` 注入；新增 loopback Node 静态 origin、固定 release SHA 的 user unit 模板和显式 FFmpeg CI prerequisite 检查。
- 安全实现 release commit：`6da4f976c9143d4f880b52f055742e6ec23ce70f`（`main` 已推送）。
- 本地证据：`pnpm check`、`pnpm check:api`、`uv run ruff check .`、`uv run pytest`（67 passed, 5 skipped）、静态 origin `/`、`/create?from=smoke`、`/healthz` 均通过。

### 远端激活门

- 当前外部未登录访问 `https://video.icthub.top/` 和 `/create` 仍为 HTTP 200，说明 Cloudflare Access 应用尚未生效；在完成 Authentik OIDC/group policy 和获得该 Access application audience 前，不激活新生产链路。
- 已确认可复用的 Cloudflare team issuer 为 `https://restless-cherry-c802.cloudflareaccess.com`；`video.icthub.top` 必须使用自己的 Access application audience，不能猜测或复用错误 audience。
- 激活前基线：Pi `18935366644f25cd88224798208793ef68bbb317`；H100 `69a53842db90bb43d6785611d385dbd66e5fe028`；本地 `main` 基线 `800bd53`。

### 回滚原则

- Access 策略保持启用；不得通过恢复固定 `lan-preview` 身份来回滚。若身份链路异常，先关闭 Oneiroi public ingress，再把 Pi/H100 checkout 切回上述基线 SHA 并恢复原进程命令。
- Pi 回滚目标：原 `oneiroi-studio.service`、`oneiroi-studio-loopback.service` 和 `cloudflared-video.service`；新 user units 仅在健康检查通过后替换旧服务。
- H100 回滚目标：Gateway `127.0.0.1:18010` 和 BFF `10.30.176.95:18000` 的原 supervisor/前台启动方式；不删除 storage、temp、模型或数据库文件。

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

- 主机：`selabpi5`，Ubuntu 24.04.4，aarch64，15 GiB RAM，根盘剩余约 79 GiB。
- Cisco VPN：`ciscovpn0=10.255.101.103`，已有 `10.30.176.0/24` 路由。
- Oneiroi checkout：`/home/winbeau/oneiroi-studio`。
- 当前运行 commit：`1893536`；GitHub `main` 当前包含后续文档 commit，但运行时代码基线一致。
- `oneiroi-studio.service`：Vite preview，监听 `192.168.3.250:4173`。
- `oneiroi-studio-loopback.service`：第二个 Vite preview，监听 `127.0.0.1:4173`。
- `cloudflared-video.service`：`video.icthub.top -> 127.0.0.1:4173`。
- user linger 已开启，重启后 user services 可自动启动。
- `/healthz`、`/v1/conversations`、`/v1/compute/gpus` 从 Pi proxy 实测 HTTP 200。
- 当前 proxy target：`http://10.30.176.95:18000`。
- 当前 proxy 固定注入 `oneiroi_user=lan-preview`，所有访问者共享同一产品身份。
- 网页可被外部 fetch 到 Oneiroi HTML；不能把“页面可打开”等同于 Access/用户隔离完成。

### H100 server

- Ubuntu 24.04 容器环境，PID 1 不是 systemd；部署必须支持前台/平台 supervisor，不能依赖 systemd。
- 当前登录身份为 root；生产目标仍应使用非 root worker，但不能在本任务中切换身份。
- 地址：`10.30.176.95`，Pi 通过 Cisco VPN 可达。
- 8 × NVIDIA H100 80GB，稳定 UUID 已确认。
- 当前 GPU 0/1/2/7 空闲；GPU 3/4/5/6 使用约 13.5 GiB，Oneiroi API 将其标记为 `VRAM_ABOVE_IDLE_THRESHOLD`。
- Pi API snapshot：8 卡、4 卡 eligible；Fast/HQ capability 都声明 available。
- Oneiroi Gateway：`127.0.0.1:18010`，health 200，私有 API无身份时 401。
- Oneiroi BFF：`10.30.176.95:18000`，health 200。
- H100 checkout：`/root/wenbiao_zhao/Oneiroi`，运行 commit `69a5384`，落后 Pi runtime 修复 commit。
- Redis `127.0.0.1:6379`、PostgreSQL `127.0.0.1:5432` 正常运行。
- 当前未发现 Oneiroi Runner/worker_process/LTX inference 进程。
- 文件系统显示 100%，但仍约 9.5 GiB 可用；权重已齐、单视频几 MiB，足够受控 Fast MVP，需严格 temp cleanup/admission。
- `/data/oneiroi` 约 128 GiB，LTX Fast/HQ/Gemma 模型已存在。
- LTX code commit：`9377758131b1ffde4b7f766804590a6617bf2ab9`。
- LTX model revision：`4229404625088d21c4f112eb640fb04a0900ee25`。
- Gemma revision：`68f7ee4fbd59087436ada77ed2d62f373fdd4482`。

## 3. 当前最高风险

### P0：固定身份

`ONEIROI_API_PROXY_USER=lan-preview` 会让所有登录用户看到/写入同一 owner 的 conversation、asset 和 job。邀请注册正式开放前必须删除。

### P0：video Access 未完成验收

`video.icthub.top/*` 必须与 `comfy.icthub.top/*` 同级使用 Cloudflare Access + Authentik OIDC。仅页面可访问不算完成；必须验证未登录 challenge、group 拒绝和深链接回跳。

### 存储运行约束（不阻塞 Fast MVP）

H100 当前约 9.5 GiB 可用，但权重、Gemma、upscaler 已全部下载，单个 MP4 只有几 MiB，足够先跑 Fast E2E。禁止重新下载/复制权重；attempt temp 在 artifact 上传后立即清理，并设置低水位 admission。同学后续释放 300 GiB 只增加长期余量。

### P1：Vite preview 双实例

当前有 LAN/loopback 两个 preview，约 200 MiB 常驻内存，构建与运行耦合。上线初期可保留 loopback preview 作为临时 beta，但应尽快改 immutable dist + 静态 origin + 独立 BFF。

### P1：Pi/H100 commit 漂移

Pi `1893536`，H100 `69a5384`。任何联调前先定义同一 release SHA/contract version；不能分别 `git pull` 到不一致状态。

### P1：Runner 不在线

capability available 只证明资产/配置判断通过，不证明当前存在可执行 worker。真实 E2E 必须等待 gpu-server Runner。

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
