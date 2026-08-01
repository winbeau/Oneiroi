# 阶段 3：LTX Fast 真机 Canary

## 目标

在不恢复 Oneiroi 自有 scheduler 的前提下，通过 gpu-server Runner 完成受控 Fast I2V，并验证身份、任务、SSE、artifact 和故障恢复的完整链路。

## 前置条件

- 真实 Authentik 双用户验收通过。
- gpu-server adapter 加固完成且默认关闭。
- gpu-server Runner、Fast profile 和模型 manifest 可用。
- H100 使用稳定 GPU UUID。
- 磁盘低水位 admission 已启用；禁止自动删除未知文件。
- 明确 Oneiroi candidate SHA、gpu-server SHA、Runner/model revision 和回滚点。

## 放量阶段

### C0：Shadow inventory/capability

Oneiroi 读取 gpu-server inventory，但不创建 lease/job。

验证：

- GPU UUID、显存、eligible 和原因与实际一致。
- Runner/profile/model readiness 不被误报。
- gpu-server 不可用时 Oneiroi 显示 degraded，不影响已上线的 conversation/asset 页面。

持续至少 2–4 小时或覆盖一次 GPU 占用变化。

### C1：单用户单任务

参数固定：

- Fast；
- 720p；
- 5 秒；
- 一张首帧；
- 固定 seed；
- 并发 1；
- 禁止 HQ。

记录：

- product job ID、remote job ID、lease ID、GPU UUID；
- queue、load、generation、encoding、download 时延；
- output artifact ID/hash/size；
- temp 清理和显存回落。

### C2：失败和恢复

逐项验证：

- 用户取消；
- 页面刷新；
- SSE 断开重连；
- Pi 到 H100 VPN 短断；
- Gateway 重启；
- gpu-server API 短暂 5xx；
- Runner 重启或 heartbeat 丢失；
- storage low-water；
- job create response 丢失后重放；
- 重复点击提交。

要求未知结果进入 reconciliation，不自动重复昂贵生成。

### C3：双用户串行

用户 A、B 各提交一个任务，先串行：

- job list/get/SSE/file/manifest 互不可见。
- artifact 不串 owner。
- 取消/重试不能影响对方。
- 同一用户刷新或重新登录后仍能恢复任务。

### C4：小并发

只有 C1–C3 稳定后，才从并发 1 提高到 2。

不要根据“有 4 张 eligible GPU”直接推导并发 4；需要以 Runner、模型加载、显存、磁盘和队列时延实测决定。

## 稳定性门

建议首次放量至少满足：

- 连续 10 个 Fast job 中至少 9 个成功。
- 所有失败都有稳定 error code 和可操作文案。
- 每个 idempotency key 的远端 execution count 为 1。
- 取消最终收敛，无长期 `cancel_requested`。
- Gateway/SSE/网络中断不导致状态倒退或重复执行。
- 输出 MP4 可播放，Range 206，hash/size 一致。
- attempt temp 在完成后清理；磁盘低水位拒绝新任务。
- Pi/Gateway 内存不随 MP4 大小线性增长。
- 运行日志可从 Oneiroi job ID 定位到 gpu-server job/lease/artifact。

## 停止条件

出现任一条件立即关闭 gpu-server 开关并停止 canary：

- 重复执行同一 idempotency key。
- owner 越权或 artifact 串用户。
- artifact hash/size 不一致仍标记 succeeded。
- Runner 不在线但 session/job 显示 ready。
- remote releasing/lost 与本地 released/succeeded 不一致。
- 磁盘进入低水位但仍接受新任务。
- 无法确定昂贵任务是否已执行却准备自动 retry。

## 回滚

- 关闭 `ONEIROI_GATEWAY_GPU_SERVER_ENABLED`。
- 恢复上一个已知安全 runtime SHA。
- 保留 Access、conversation、asset 和 product job 数据。
- 不恢复浏览器身份注入，不自动启动旧 Oneiroi Runner。
- 对在途 remote jobs 执行只读对账，禁止直接重提。

## 预计时间

1–3 天，不确定性约 ±60%；最大变量是 gpu-server Runner、CUDA/LTX 首次加载和 H100 资源状态。
