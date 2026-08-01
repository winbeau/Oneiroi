# M9：首尾帧、热加载与 GPU 释放 E2E 证据

> 验证时间：2026-08-02；范围：H100 loopback/内网 canary。

## 验证版本

- Oneiroi：`30a56ef`
- gpu-server：`53272a9`
- LTX code：`9377758131b1ffde4b7f766804590a6617bf2ab9`
- profile：`ltx23-distilled-fast-v1`

## 脚本扩展

`scripts/test-private-api.sh` 现在支持：

```bash
ONEIROI_PRIVATE_API_FIRST_FRAME=/absolute/head.png
ONEIROI_PRIVATE_API_LAST_FRAME=/absolute/tail.png
```

脚本会分别上传首帧和尾帧，将 `firstFrameAssetId`、`lastFrameAssetId` 提交到 Oneiroi job，并继续验证 conversation、compute SSE、job SSE、MP4、manifest 和 release。

## 产品链路

```text
Oneiroi BFF 127.0.0.1:18001
  -> Oneiroi Gateway 127.0.0.1:18011
  -> scoped Oneiroi gpu-server client
  -> gpu-server 127.0.0.1:8300
  -> fenced hot LTX child on GPU UUID
  -> authenticated artifact stream
  -> Oneiroi asset/history/file/manifest
```

本次 transient canary 不修改生产 `18000/18010` 服务。

## 成功标识

- conversation：`conversation-4e3268b0e7f74e79`
- compute session：`compute-33b4952d19cd439d`
- Oneiroi job：`job-f1dbf6c40c1343149c40`
- result asset：`asset-57c8e83fd2dc44219575`
- gpu-server job：`3bebc8e6-c5c1-45d3-aae8-97f123056f9e`
- gpu-server lease：`2b35acb5-6a90-4d0f-9d4c-5e7a3583c742`
- gpu-server artifact：`56d9677d-c5a7-4c0d-888d-cd84be85358b`

## 视频验证

```text
codec: h264
resolution: 1280x704
frames: 121
fps: 24
duration: 5.041667 seconds
size: 2,394,811 bytes
sha256: bf1046c94d304311e977ea9f94bb38d2319a0572782a0cdca2728c1fa8dcab99
```

- Range 返回 HTTP 206 和 MP4 `ftyp`；
- public manifest 同时包含 first/last artifact ID；
- public manifest 不含 path key；
- attempt temp 在完成后为空。

首尾帧方向性 SSIM：

```text
首输出 vs 首输入：0.574930
首输出 vs 尾输入：0.539164
尾输出 vs 尾输入：0.559621
尾输出 vs 首输入：0.529858
```

首输出更接近首输入，尾输出更接近尾输入。

## 热加载和释放

修复前发现：

1. gpu-server 自己的 hot model child 被 API NVML inventory 判为 foreign process，第二个同 lease job 一直 queued；
2. lease 已 released 时，长驻 worker 不会主动 unload child。

修复后：

- 冷 job 和第二个热复用 job 使用同一 child PID `90423`；
- 第二个 job 成功，不再被 foreign-process admission 阻断；
- lease release 后 worker 自动卸载 stale-fence child；
- GPU 0 返回 `0 MiB`；
- Redis managed PID registry 返回 0；
- 其他实验占用的 GPU 3/4/5/6 未被选择或修改。

## 事件与状态

gpu-server durable events 覆盖：

```text
accepted -> queued -> assigned -> loading_model -> running -> encoding -> succeeded
```

Oneiroi job 到 `succeeded/100`，compute session 与底层 gpu-server lease 均到 `released`。`cancel_requested` 仍未被当作 `cancelled`。

## 自动检查

```text
Oneiroi Ruff: passed
Oneiroi pytest: 69 passed, 5 skipped
Oneiroi frontend lint/typecheck/build: passed
gpu-server Ruff: passed
gpu-server pytest: 36 passed, 1 skipped
gpu-server GitHub CI: passed
```
