# M10：192.168.3.250 内网原型

> 激活时间：2026-08-02。公网 Oneiroi Tunnel 暂停，认证暂不作为本阶段验收门。

## 当前入口

```text
http://192.168.3.250:4173
```

仅 Web origin 监听 `192.168.3.250:4173`；Pi BFF 仍只监听 `127.0.0.1:8000`。浏览器 API、SSE、上传和 Range 均经同源 static origin 代理，不向局域网直接暴露 BFF。

公网 `cloudflared-video.service` 已 `disabled/inactive`。系统级 Cloudflare Tunnel 配置不包含 `video.icthub.top`，其余 login/register/comfy 域名未修改。

## 运行链路

```text
LAN browser
  -> Pi static origin 192.168.3.250:4173
  -> Pi BFF 127.0.0.1:8000 (temporary development identity)
  -> H100 BFF 10.30.176.95:18000 (service assertion required)
  -> H100 Gateway 127.0.0.1:18010
  -> gpu-server 127.0.0.1:8300
  -> fenced LTX Fast worker on GPU UUID
```

H100 Gateway 启用：

```text
ONEIROI_GATEWAY_GPU_SERVER_ENABLED=true
ONEIROI_GATEWAY_GPU_SERVER_BASE_URL=http://127.0.0.1:8300
ONEIROI_GATEWAY_GPU_SERVER_REQUEST_TIMEOUT_SECONDS=1800
```

Oneiroi scoped token 只存在于 H100 mode-600 配置，未写入 Git、日志或命令参数。

## 版本

- Oneiroi Pi/H100 runtime：`64e5a18`
- Oneiroi main test cleanup：`0b3a994`
- gpu-server：`fff1627`

## 发现并修复的问题

真实 LAN multipart 图片上传返回 502。根因有两层：

1. static origin 使用 undici streaming request body 时，大文件 multipart 代理不稳定；
2. curl 对约 2.5 MiB multipart 使用 `Expect: 100-continue`，该 header 不能传给 undici fetch。

修复：

- API 请求体使用默认 20 MiB 有界缓冲，超过限制返回 413；
- response、MP4 和 SSE 继续流式转发；
- 过滤 `Expect` 和原始 `Content-Length`，由 fetch 重新生成；
- 增加 multipart、`100-continue`、413 和 HTTP Range origin 集成测试。

提交：

- `f4eebfd Fix bounded multipart proxying in static origin`
- `64e5a18 Handle multipart continue through static origin`

另外补齐 scheduler tests 的 `ComputeSessionService.close()`，消除 pytest 结束时 pending lease-renewal task：`0b3a994`。

## 真实 LAN E2E

- owner：`lan-prototype-e2e-v2`
- conversation：`conversation-f903f9e5bd4c45ab`
- compute session：`compute-04766230aae3432d`
- Oneiroi job：`job-db00b98e14d64ea2a84f`
- Oneiroi result asset：`asset-fb210d31c18542ac8c7f`
- gpu-server job：`4597f860-ee49-4a06-bd3e-a4c562ef65dd`
- gpu-server artifact：`9f2149f5-847a-45fa-a74b-d2710f4ca36b`

输出：

```text
container: mov,mp4,m4a,3gp,3g2,mj2
duration: 5.042 seconds
size: 2,394,800 bytes
sha256: 8779373f35224f868cdd7f9726f561e0180b6dd4de90527906ae7fa4bb6ef258
```

验证通过：

- conversation POST/GET/PUT 和 owner 隔离；
- GPU inventory、compute session、snapshot 和 SSE；
- 首帧与尾帧 multipart upload；
- Fast I2V product job 和 durable SSE；
- public manifest 无本地 path；
- MP4 authenticated download 和 32-byte Range 206；
- compute/gpu-server lease release；
- GPU 0 返回 0 MiB，managed process registry 为 0；
- 服务重启后 job/history/Range 仍可读取。

取消链：

- job：`job-dc0dba60b6f946a898e7`
- session：`compute-f03fa2ea34eb43d0`
- 最终状态：`cancelled`，不是仅停留在 `cancel_requested`；
- release 后 GPU 0 为 0 MiB。

真实 Chromium LAN smoke 通过 `/`、`/inspiration`、`/assets`、`/create`，并完成 UI 热加载和释放，无 console error。

## 质量门

```text
Ruff: passed
pytest: 69 passed, 5 skipped
pending lease-renewal warning: eliminated
frontend lint/typecheck/build: passed
static origin integration test: passed
Oneiroi CI: passed
```

## 运行与回滚

Pi 已为原 unit/env 创建带 UTC 时间戳的备份；H100 `gateway-env.json` 同样存在 mode-600 时间戳备份。

恢复公网前必须同时完成：

1. Pi BFF 恢复 production Access JWT 配置；
2. Web listener 恢复 `127.0.0.1:4173`；
3. 重启 BFF/Web 并验证伪造 cookie/header 返回 401；
4. 最后才 `systemctl --user enable --now cloudflared-video.service`。

不得在 development identity 仍启用时恢复公网 Tunnel。
