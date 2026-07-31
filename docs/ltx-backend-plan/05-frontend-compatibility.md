# 前端兼容与交互改造

> 本文件是 [LTX-2.3 动态 H100 主计划](../ltx-desktop-inspired-backend-plan.md) 的模块子计划。跨模块范围、阶段顺序和里程碑以主计划为准。

## 前端修改方案

### 新增 ComputeControl

在生成页 header 或 Composer 上方增加紧凑资源控制条：

#### 空资源

```text
GPU 资源未加载                         [热加载]
```

#### 加载中

```text
正在热加载 2/4
GPU 0 Fast：moving weights 68%
GPU 1 Fast：ready
GPU 2 HQ：loading checkpoint
GPU 7 HQ：waiting
```

#### Ready

```text
4 张 H100 已就绪 · Fast 2 · HQ 2       [释放资源]
```

#### Degraded

```text
3/4 张 H100 已就绪 · Fast 2 · HQ 1
1 张卡被其他任务占用                   [查看详情] [释放资源]
```

建议新增目录：

```text
apps/web/src/features/compute/
├─ compute-control.tsx
├─ gpu-selector-popover.tsx
├─ compute-session-panel.tsx
├─ release-compute-dialog.tsx
├─ slot-status-row.tsx
├─ hooks.ts
└─ types.ts  # 最终由 OpenAPI 生成类型替代
```

### 热加载弹窗

字段：

- 选卡方式：自动 / 手动；
- 卡数：默认 4，最大值来自后端；
- 动态 GPU 列表：物理 index、型号、显存、占用、是否 eligible；
- profile 预览：例如 `2 Fast + 2 HQ`；
- `allowPartial`：默认开启；
- 加载后预计占用提示。

前端只能提交后端返回的 GPU ID；后端仍要重新校验，不能信任列表已过期前的空闲状态。

### Fast/HQ 控件改造

Composer 不再用本地常量决定质量档：

- 从 `/v1/compute/capabilities` 读取 profile 和参数矩阵；
- 无 compute session 时禁用“生成”，提示先热加载；
- session loading 时展示加载状态；
- 只有 1 张卡时禁用 HQ，并显示“HQ 至少需要 2 张已分配 GPU”；
- HQ slot 没 ready 时禁用 HQ，而不是提交后静默改 Fast；
- 后端返回参数归一化结果后，UI 更新实际 resolution/frame count。

这沿用 Desktop 的“后端提供 model specs、前端只渲染有效组合”模式。

### 任务卡改造

现有 JobTimeline 增加真实阶段：

- loading model；
- Prompt 编码；
- diffusion step；
- stage-2/upscale；
- encoding。

任务卡展示：

- assigned GPU，例如 `GPU 2 · H100 80GB`；
- Fast/HQ profile；
- warm start / cold recovery；
- queue position；
- current step / total steps；
- cancel requested 与真正 cancelled 的区别；
- 后端错误码对应的可操作提示。

### 释放交互

点击“释放资源”后：

- 没有活跃任务：直接确认并展示逐卡 unloading；
- 有运行任务：默认只允许“任务完成后释放”；
- “取消任务并释放”放在危险操作区并二次确认；
- UI 等到 `compute.session.released` 才显示显存已经释放；
- 如果某卡显存未回落，显示具体 slot error，不能直接把界面变成 empty。

### 状态管理

- TanStack Query：GPU inventory、capabilities、compute session、jobs/assets 的服务端状态；
- Zustand：仅保存 Composer 草稿、会话选择和 UI 展开状态；
- SSE：实时更新 compute session 和 job；断线后用 `Last-Event-ID` 或 GET snapshot 恢复；
- 页面刷新：根据服务器 active compute session 和 jobs 重建 UI；
- 不再用浏览器 timer 推进真实任务。

### 取消生产环境模拟 fallback

当前前端在任务创建或 SSE 失败后会静默进入浏览器模拟成功流程。应改为：

- `VITE_DEMO_MODE=true` 时才启用显式 Demo 模式；
- production 构建中 API 失败就是失败；
- UI 明确展示 BFF/Gateway 不可用；
- 不创建假的成功资产。

### OpenAPI 类型生成

参考 Desktop：

1. Gateway 用 Pydantic 定义 API DTO；
2. CI 导出 OpenAPI；
3. 生成 TypeScript types/client；
4. 前端禁止手写重复的 compute/job response 类型；
5. Runner 控制消息使用 `oneiroi_common` 中的 Pydantic contract，并做运行时校验。

---

[返回主计划](../ltx-desktop-inspired-backend-plan.md)
