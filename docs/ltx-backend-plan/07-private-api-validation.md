# 私网 GET、POST、PUT 集成验证计划

> 本文件是 [LTX-2.3 动态 H100 主计划](../ltx-desktop-inspired-backend-plan.md) 的模块子计划，定义 P7/M8 的测试边界。目标是在不创建公网入口、不修改 Cloudflare Tunnel/DNS、不绑定公网接口的前提下验证真实 API。

## 1. 验证目标

最终必须同时完成两类验证：

1. **进程内集成测试**：使用 FastAPI ASGI client/TestClient 验证鉴权、DTO、持久化和方法语义，不监听任何 TCP 端口。
2. **真实 loopback smoke test**：在目标主机上仅绑定 `127.0.0.1`，使用 `curl --noproxy '*'` 验证真实 HTTP GET、POST、PUT 和 SSE/下载链路。

本阶段不是公网发布阶段。测试成功不代表 API 可以通过 `video.icthub.top`、Cloudflare Tunnel 或公网 DNS 对外开放。

## 2. 禁止的暴露方式

测试期间禁止：

- 为 API 新建 Cloudflare Tunnel ingress；
- 修改 `video.icthub.top` 或其他公网 DNS；
- 把 Gateway/BFF 测试端口绑定到 `0.0.0.0`；
- 在 Docker Compose 中发布 `0.0.0.0:<port>:<port>`；
- 修改路由器端口转发、UPnP、NAT 或防火墙公网入站规则；
- 使用公网域名执行 smoke test；
- 为了测试临时关闭鉴权；
- 把开发身份 header 作为生产身份机制；
- 输出 cookie、token、内部签名密钥或完整用户隐私数据到日志。

如果必须监听 TCP，默认地址必须是：

```text
127.0.0.1
```

需要 Pi → H100 联调时，可以使用已配置的实验室私网地址，但端口只允许在可信私网接口监听，并且不得进入 Cloudflare ingress。优先通过 SSH 在目标主机本地执行测试。

## 3. PUT 资源设计

现有任务提交后参数不可变，Compute release 是动作，因此都不适合为了“有 PUT”而强行使用 PUT。

选择 Conversation 的完整可变表示作为幂等 PUT 资源：

```http
PUT /v1/conversations/{conversation_id}
Content-Type: application/json
```

```json
{
  "title": "更新后的创作会话"
}
```

语义：

- conversation ID 由既有 POST 创建；
- PUT 完整替换当前允许修改的会话字段，首版只有 `title`；
- 重复发送同一个 payload 不创建新资源；
- 返回更新后的 `ConversationResponse`；
- 更新 `updatedAt`，但不能改变 owner；
- 非 owner 返回 404，避免泄露资源存在性；
- 不支持由客户端通过 PUT 创建任意 ID；不存在时返回 404；
- 字段校验失败返回 422；
- BFF 与 Gateway 都必须有契约和测试。

对应读取和创建：

```http
POST /v1/conversations
GET  /v1/conversations
GET  /v1/conversations/{conversation_id}
PUT  /v1/conversations/{conversation_id}
```

## 4. 非破坏性 GET/POST/PUT 测试链

这条链不启动模型、不占用 GPU，适合每次部署后的基础 smoke test。

### 4.1 GET health/capabilities

```bash
BASE_URL=http://127.0.0.1:18000
curl --noproxy '*' --fail-with-body "$BASE_URL/healthz"
curl --noproxy '*' --fail-with-body "$BASE_URL/v1/compute/capabilities"
```

### 4.2 POST conversation

```bash
CREATE_RESPONSE="$(
  curl --noproxy '*' --fail-with-body \
    -H 'Content-Type: application/json' \
    -X POST \
    -d '{"title":"Private API smoke"}' \
    "$BASE_URL/v1/conversations"
)"
```

从响应中读取服务端生成的 conversation ID，不在脚本中硬编码。

### 4.3 PUT conversation

```bash
curl --noproxy '*' --fail-with-body \
  -H 'Content-Type: application/json' \
  -X PUT \
  -d '{"title":"Private API smoke updated"}' \
  "$BASE_URL/v1/conversations/$CONVERSATION_ID"
```

相同 PUT 至少重复执行一次，验证：

- 仍是同一个 ID；
- 没有产生重复 conversation；
- title 为最终提交值；
- owner 没有变化。

### 4.4 GET 验证

```bash
curl --noproxy '*' --fail-with-body \
  "$BASE_URL/v1/conversations/$CONVERSATION_ID"

curl --noproxy '*' --fail-with-body \
  "$BASE_URL/v1/conversations"
```

脚本必须用 `jq -e` 或 Python 断言 JSON 字段，不能只凭 HTTP 200 判断通过。

## 5. Compute session 私网验证

只有 P0–P4 的自动化测试全部通过，并且实时 inventory 确认存在 eligible GPU 后，才能进行真实资源测试。

### 5.1 GET inventory

```http
GET /v1/compute/gpus
```

验证：

- 默认请求数为 4；
- 最大分配数为 4；
- GPU 以 UUID 标识；
- 外部占用卡 `eligible=false`；
- 不假设空闲卡 index 连续。

### 5.2 POST 一卡 session

真实 smoke test 先申请 1 张卡：

```json
{
  "requestedGpuCount": 1,
  "selectionMode": "auto",
  "gpuIds": [],
  "profilePolicy": "balanced",
  "allowPartial": true
}
```

验证：

- 实际只租约一张 eligible GPU；
- profile plan 为 1 Fast + 0 HQ；
- capabilities 返回 `HQ_REQUIRES_AT_LEAST_2_GPUS`；
- 没有外部进程被终止或抢占；
- session 事件可观察 loading → ready 或明确 failed。

### 5.3 GET session/SSE

验证：

- GET snapshot 与 SSE 最终状态一致；
- SSE 断线后可通过 snapshot 恢复；
- slot 包含 GPU UUID、physical index、profile 和加载阶段；
- ready 前任务不能进入 generating。

### 5.4 POST release

使用默认策略：

```json
{
  "policy": "when_idle"
}
```

验证：

- session 进入 draining/releasing/released；
- Model Worker 子进程退出；
- GPU 租约清除；
- NVML 显存回到配置基线；
- 没有 orphan CUDA process。

完成单卡验证后，才允许根据实时空闲数量测试 2–4 卡；空闲不足不是失败，不得抢占其他任务。

## 6. 监听面验证

启动测试服务后必须检查：

```bash
ss -ltnp
```

验收条件：

- 测试端口仅出现在 `127.0.0.1:<port>` 或明确批准的私网接口；
- 不出现 `0.0.0.0:<test-port>`；
- 不出现 `[::]:<test-port>`；
- Cloudflare 配置没有新增测试端口 ingress；
- 测试结束后临时服务和端口已关闭。

若使用 Docker：

```bash
docker ps --format '{{.Names}}\t{{.Ports}}'
```

端口发布必须类似：

```text
127.0.0.1:18000->8000/tcp
```

不能是：

```text
0.0.0.0:18000->8000/tcp
```

## 7. 自动化测试矩阵

### GET

- health；
- GPU inventory；
- capabilities；
- conversation list/detail；
- compute session snapshot；
- job snapshot；
- manifest/file 授权。

### POST

- conversation create；
- compute session create，含 Idempotency-Key；
- upload/asset create；
- I2V job create；
- cancel；
- release。

### PUT

- conversation title replacement；
- 重复 PUT 幂等性；
- 非 owner 404；
- 不存在资源 404；
- 空 title/超长 title 422；
- BFF → Gateway identity 保持。

### 安全负例

- 无身份；
- 错误 owner；
- 任意服务器路径；
- 超大上传；
- 非法 MIME；
- 未 ready 时提交 HQ；
- 只有 1 卡时提交 HQ；
- 外部占用 GPU 手动选择；
- release 他人的 session；
- 重放错误 Idempotency-Key payload。

## 8. 测试产物

将脚本和自动化测试落在：

```text
scripts/test-private-api.sh
services/gateway/tests/integration/
apps/bff/tests/integration/
```

测试报告只保存：

- HTTP 方法、路径、状态码；
- 去敏后的资源 ID；
- 断言结果；
- session/job terminal state；
- GPU UUID 的截断显示；
- 显存基线与释放后数值。

不得保存：

- token/cookie；
- 完整内部签名；
- 用户上传原图；
- 生成视频二进制；
- 模型权重路径之外的敏感主机信息；
- 其他用户进程的完整命令行。

## 9. 完成标准

P7/M8 只有在以下条件全部满足时完成：

- ASGI GET/POST/PUT 集成测试通过；
- loopback GET/POST/PUT smoke test 通过；
- PUT 重复执行验证幂等；
- 一卡 Compute session 热加载/释放在私网完成，或因没有 eligible GPU 明确记录阻塞；
- 测试端口未绑定公网接口；
- 没有新增 Cloudflare/DNS/路由器入口；
- 临时服务已关闭；
- `ss`/Docker 端口检查通过；
- 日志和报告不包含凭据或媒体内容；
- `uv run ruff check .`、`uv run pytest` 和适用的 `pnpm check` 通过。

---

[返回主计划](../ltx-desktop-inspired-backend-plan.md)
