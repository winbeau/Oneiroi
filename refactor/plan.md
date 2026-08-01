# Oneiroi 重构执行计划

## 保留

- React SPA、TanStack Query/Zustand 边界；
- BFF 显式 route allowlist；
- conversation/job/asset 产品模型；
- compute session/job 独立状态机；
- stable GPU UUID、lease/fencing、Runner supervisor 的语义；
- Fast/HQ capability gating、snapshot + SSE。

## O0：冻结契约

`resources/current-contracts/` 保存当前 `compute.py.txt`、`generation.py.txt`、`runner_protocol.py.txt` 快照。源代码仍是权威；快照用于设计 `gpu-server` adapter 和 diff，禁止运行时 import。

## O1：生产身份

- BFF 验证 Cloudflare Access JWT/可信 identity header；
- `(issuer, subject)` 映射内部 user；
- session cookie 使用 HttpOnly/Secure/SameSite/expiry；
- mutation CSRF；
- BFF→Gateway/gpu-server 使用 service auth；
- 直接访问私有 Gateway 失败。

## O2：算力边界

保留 Gateway ports，新增 `HttpGpuServerComputeBackend` 与 `HttpGpuServerJobExecutor`。route handler 不直接调用远端。Oneiroi 继续拥有 conversation、产品 job、用户 asset 和产品 SSE；gpu-server 拥有 lease、attempt、worker 和执行状态。

## O3：artifact 协议

删除跨服务 `inputPaths/outputPath/manifestPath`：

- 输入使用 artifact ID/签名 URL；
- 输出使用 artifact ID、SHA-256、size、media type；
- BFF 下载流式转发并支持 Range/ETag；
- 浏览器断开中止上游；
- Pi 不缓存长期视频。

## O4：恢复与取消

- compute events 持久化或直接消费 gpu-server durable events；
- Gateway 重启用 snapshot + Last-Event-ID 恢复；
- cancel_requested 与 cancelled 分离；
- worker/VPN/Redis/PostgreSQL 故障均有对账规则；
- 不自动重复未知是否完成的昂贵任务。

## O5：Pi 生产部署

CI 构建 SPA，Caddy 提供 dist，BFF 使用 loopback systemd，cloudflared 独立 unit。增加 release directory、health、日志、回滚、VPN route/MTU/DNS 检查。

## O6：产品完善

参考即梦的功能信息架构而不复制品牌/源码：灵感流、文/图/首尾帧视频、提示词增强、队列、历史、结果复用。视觉复用 `resources/design-system/` 的 token 和 motion primitive，清理 Feiyue 业务变量。

## O7：仓库迁移

- 将嵌套 `LTX-2` 替换为 commit/model manifest 或 submodule；
- 移除完整 `xju-feiyue` 嵌套仓库，保留来源/许可证；
- 备份 Actions secrets/variables/environment/webhook；
- 使用 GitHub transfer 将 `winbeau/Oneiroi` 移至 `xjuIcthub/Oneiroi`。

## 完成门

- cookie/header 无法冒充其他用户；
- 独立文件系统部署可完成 Fast/HQ；
- Pi 内存不随 MP4 大小线性增长；
- 重启/断网不重复生成；
- 嵌套仓库不进入生产包与 CI；
- transfer 后历史、Issues、Actions 和 release 可用。
