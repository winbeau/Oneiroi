# 模块 4：图片理解、生成与资产化

## 1. 目标

让 Agent 安全使用用户已有图片，并在 provider 支持时生成参考图片；所有输出统一进入现有 Asset 域，成为视频首帧/尾帧的可授权资源。

## 2. 能力分层

图片功能拆为两个独立 capability：

1. `image_input`：GPT 分析已有图片；
2. `image_generation`：GPT/provider 生成新图片。

两者分别 probe、配置和显示。图片生成不可用时，文本与图片理解 Agent 仍可运行。

## 3. 已有图片输入

流程：

1. 前端只发送 asset ID；
2. Gateway 用当前 owner 查询 AssetService；
3. 只允许受支持的 image media type；
4. Pillow decode 并限制像素、尺寸和总字节；
5. 规范化方向，必要时降采样；
6. 以内联 data URL 或 provider 支持的受控上传方式发送；
7. 不把 storage path、H100 地址或授权下载 URL交给模型。

首版限制建议：

- 每 run 最多 4 张；
- 单张最多 20 MiB；
- 总像素和最长边可配置；
- GIF/动画只使用首帧或明确拒绝；
- EXIF 等非必要 metadata 不发送。

## 4. 图片生成工具

`generate_reference_image` 输入 schema：

```json
{
  "prompt": "string",
  "negativePrompt": "string|null",
  "purpose": "first-frame|last-frame|style-reference",
  "ratio": "16:9|9:16|1:1",
  "count": 1,
  "referenceAssetIds": []
}
```

模型不能指定：

- provider base URL；
- 本地文件路径；
- 输出目录；
- owner ID；
- 任意下载 URL；
- 未配置 model。

## 5. Provider 返回处理

支持模式按优先级：

1. base64/image bytes；
2. provider file ID，通过固定 provider client 拉取；
3. provider URL，仅在固定 scheme/host allowlist、禁止 redirect 到私网的条件下拉取。

禁止模型提供任意 URL 让 Gateway 下载。

对输出执行：

- 有界流式读取；
- 内容类型 sniff，不只信 header；
- Pillow `verify()` + 完整 decode；
- 限制像素炸弹；
- 转换为允许格式 PNG/WebP；
- strip metadata；
- 计算 SHA-256 和 size；
- `.partial` 写入后原子 rename；
- 失败时删除 partial。

## 6. ArtifactService 扩展

新增类似：

```python
create_generated_image(
    owner_id,
    image_bytes,
    title,
    provenance,
) -> AssetResponse
```

provenance 包含：

- `sourceType=agent-image`；
- agent run/tool call ID；
- provider/model；
- prompt hash，而非默认公开完整 prompt；
- ratio/width/height；
- provider request/response ID；
- safety outcome；
- 创建时间。

完整 prompt 是否进入用户可见 metadata 由产品策略决定；日志只记录 hash/长度。

## 7. 图片与 draft 的关系

生成完成后不自动覆盖 draft：

- UI 显示新 Asset 卡片；
- 用户可选择“设为首帧”“设为尾帧”或“仅保存”；
- 采用动作把 asset ID 写入 Zustand draft；
- 提交视频 Job 时由现有 JobService 再次 owner 校验；
- 删除被 draft/job 引用的 asset 仍遵循现有或后续引用保护。

## 8. 连续性 Agent 操作

推荐 Agent 支持：

- 根据已有首帧生成尾帧描述；
- 分析首尾帧主体、构图、光线和身份一致性；
- 提出 motion prompt，不声称实际视频结果；
- 生成 first-frame/last-frame 候选；
- 比较候选并解释差异；
- 将最终候选交给用户确认。

不在首版自动批量生成大量候选。

## 9. Safety 和失败语义

- provider safety refusal 原样映射为稳定错误，不尝试绕过；
- 用户看到可操作但不泄漏内部 policy 的说明；
- 生成 0 张、返回损坏图片或格式不符均为失败；
- 部分成功时保存已验证图片，并在 tool result 标记 partial；
- 图片工具失败不应使整个 Conversation 不可用；
- provider 断流后不把 partial 当正式 Asset。

## 10. 配额与成本

首版建议：

- 每次审批最多 2 张；
- 每 run 最多 4 张；
- 每 owner 同时最多 1 个图片调用；
- 每日图片数量/成本可配置；
- 达到额度返回 429 + `AGENT_IMAGE_QUOTA_EXCEEDED`；
- UI 审批卡展示数量、尺寸和“将调用外部生成服务”。

## 11. 测试

- base64、file ID 和 allowlisted URL fixture；
- 重定向到 loopback/private IP 必须拒绝；
- 超大、截断、畸形、像素炸弹图片返回 422；
- 跨 owner reference asset 返回 404；
- provider 返回重复图片时按 tool call/idempotency 不重复资产化；
- partial 文件在失败后清理；
- Asset Range、下载和删除仍通过现有测试；
- 图片生成不可用时 capability 和 UI 正确降级。

## 12. 完成门

- 图片输入和输出都不暴露 storage path；
- 只有当前 owner 的 asset 可送入模型；
- 每张生成图片经过完整解码、大小限制和 SHA-256；
- 图片只在审批后生成；
- 生成结果作为真实 Asset 持久化并可用于首尾帧；
- 失败/取消不会留下公开 partial 或伪成功记录；
- image capability 关闭不影响文本 Agent 和现有上传链路。
