# Oneiroi Studio 前端美化与动效改造计划

> 状态：**已实施**。视觉底座、壳层导航、灵感页、生成舞台、Composer、任务时间线、资产作品墙与预览均已完成；测试通过后部署到 `pi5`。

## 实施结果

| 阶段 | 状态 | 结果 |
| --- | --- | --- |
| Phase A | 已完成 | 暖白纸张 Token、梦境紫品牌色、Serif/Sans 层级、Motion 与 reduced-motion |
| Phase B | 已完成 | 独立字标、共享导航胶囊、页面转场、Notion 会话栏 |
| Phase C | 已完成 | 编辑式 Hero、叠帧展示、动态分类与非对称模板卡 |
| Phase D | 已完成 | Keyframe Stage、Agent 命令条、悬浮 Composer、高级参数 Popover、任务时间线 |
| Phase E | 已完成 | 资产作品墙、吸附筛选、布局动画与资产预览 Dialog |
| Phase F | 进行中 | 完整检查、提交、推送与 `pi5` 部署 |

## 1. 改造目标

将当前“功能完整但偏工程后台”的界面，重做成：

- **xju-feiyue 式丝滑 Notion 质感**：暖白纸张、克制边框、编辑感排版、低对比层级、轻阴影、稳定的 150/600ms 动效体系。
- **即梦主页式创作氛围**：视觉内容优先、悬浮创作器、分层舞台、卡片渐进出现、任务状态有连续反馈、页面切换不生硬。
- **Oneiroi 独立品牌**：不复制第三方 Logo、图片、插画、文案和源码；保留“灵感 → 生成 → 资产”、Agent、首尾帧、任务和资产功能。

## 2. 当前界面问题

### 2.1 全局

- 大面积纯白和细线平均分布，视觉中心不明确，像普通管理后台。
- 当前亮蓝色作为唯一强调色，品牌辨识度弱，按钮、链接、进度条看起来来自同一套默认组件。
- 标题、说明、工具栏、卡片正文的字号和灰度差距偏小，缺少“编辑内容 > 工具 > 元信息”的层级。
- 圆角、阴影、背景色虽然统一，但组合后偏厚重；卡片太像独立盒子，缺少 Notion 的“页面块”感。
- 除图片轻微缩放、旋转图标和进度条外，几乎没有页面级编排和状态过渡。

### 2.2 生成页

- 中央空状态占据过多空间，首尾帧与 Prompt 被挤在底部，创作关系不直观。
- Agent 区域像普通通知卡，未形成“智能创作入口”。
- Composer 信息密度高，但首尾帧、Prompt、规格、增强和提交按钮竞争注意力。
- 任务卡是纵向后台记录样式，缺少“镜头正在被创作”的视觉反馈。

### 2.3 灵感页

- Hero、分类、卡片网格都是静态矩形堆叠，没有主推模板和节奏变化。
- 图片是最重要的信息，却被标题、按钮和标签平均分走注意力。
- 移动端首屏 Hero 偏高，用户需要滚动较远才看到模板。

### 2.4 资产页

- 工具栏和内容区层级接近文件管理器，缺少创作作品库的沉浸感。
- 卡片操作始终占位，图片没有成为视觉主体。
- 网格/列表切换是瞬时重排，缺少位置和尺寸过渡。

## 3. 设计方向：Notion × Dream Studio

### 3.1 视觉关键词

- 纸张感、编辑感、安静、精确
- 视觉内容优先、工具按需出现
- 浮层轻、边框淡、阴影短
- 动效有编排，不追求炫技
- 只有正在执行的任务保留持续运动

### 3.2 色彩系统

将纯白后台改成暖中性色基底，并建立 Oneiroi 梦境紫品牌色：

```css
--canvas: #fbfaf8;
--paper: #ffffff;
--paper-subtle: #f6f4f0;
--paper-hover: #f1efeb;
--ink: #302e2a;
--ink-muted: #716f69;
--ink-faint: #a09d96;
--line: rgba(48, 46, 42, 0.09);
--line-strong: rgba(48, 46, 42, 0.16);
--dream: #665ccf;
--dream-hover: #574dbd;
--dream-soft: rgba(102, 92, 207, 0.10);
--success: #24796b;
--warning: #b7791f;
```

原则：

- 80% 中性色，15% 图片内容色，5% 品牌色。
- 品牌紫只用于主 CTA、焦点、选中态、进度和少量 Agent 标记。
- 状态色使用低饱和浅底，不使用大面积高纯度蓝绿红。

### 3.3 字体与排版

- UI：`Inter Tight / PingFang SC / system-ui`。
- 展示标题：`Source Serif 4 / Noto Serif SC / serif`，仅用于 Hero、空状态和页面标题。
- 数值与任务 ID：等宽字体。
- 页面标题使用 Serif，按钮、导航、参数和任务信息使用 Sans，形成编辑内容与工具的区别。
- 中文正文行高提升到 1.65；元信息减小并降低对比度。
- 字体优先自托管，避免 Pi 部署依赖 Google Fonts。

### 3.4 圆角、边框与阴影

- 小控件：6px；卡片：10px；悬浮创作器：16px；Hero：20px。
- 默认卡片只使用淡边框或极轻阴影，两者不同时强化。
- 悬浮组件阴影：短距离、低透明度，不使用大面积灰雾。
- 图片卡片的圆角主要给媒体区域，正文尽量像页面块而不是厚重容器。

## 4. 动效系统

参考 xju-feiyue 已有的节奏：微交互 150ms、入场 600ms、主缓动 `cubic-bezier(0.2, 0.8, 0.2, 1)`；结合 AI 创作首页的分层与连续反馈。

### 4.1 时间与缓动

| 类型 | 时长 | 用途 |
| --- | --- | --- |
| Instant | 100–140ms | 按压、图标、颜色切换 |
| Micro | 160–220ms | Hover、菜单、Tooltip、输入聚焦 |
| Layout | 280–360ms | 侧栏、筛选、网格/列表重排、展开面板 |
| Entrance | 480–620ms | 页面、Hero、卡片列表入场 |
| Progress | 700–1200ms | 任务进度、结果揭示 |

统一缓动：

```css
--ease-out-expo: cubic-bezier(0.2, 0.8, 0.2, 1);
--ease-soft: cubic-bezier(0.22, 1, 0.36, 1);
```

### 4.2 技术选择

建议增加 `motion`（Motion for React）：

- 用于路由页淡入、共享选中胶囊、卡片 stagger、布局重排和侧栏弹簧。
- CSS 继续负责颜色、阴影、简单 hover、进度 shimmer。
- IntersectionObserver 只用于灵感页首屏以下的渐进出现。
- 所有动画只改 `transform`、`opacity`，避免滚动卡顿。
- 完整支持 `prefers-reduced-motion`，降级后内容直接显示终态。

### 4.3 动效清单

1. **页面切换**：旧页淡出 4px，新页从 8px 下方淡入；不做整屏滑动。
2. **主导航**：选中态从下划线改为共享浅色胶囊，跨导航平滑移动。
3. **Hero 入场**：Eyebrow → 标题 → 描述 → 搜索框按 70–90ms 级联出现。
4. **灵感卡片**：首屏 stagger；Hover 上浮 4px、图片放大 1.025、操作层淡入。
5. **Composer 聚焦**：输入聚焦后轻微抬升，边框过渡到品牌色，工具区逐步显现。
6. **首尾帧关系**：两张帧卡之间增加一条流动轨迹；仅 Hover/聚焦或任务运行时运动。
7. **Agent 展开**：使用高度、透明度和内容 stagger，不再瞬时出现。
8. **任务阶段**：阶段节点平滑推进；进行中使用低对比 shimmer，不用显眼旋转器作为主视觉。
9. **成功结果**：预览图从模糊占位到清晰内容 crossfade，操作按钮延迟 100ms 出现。
10. **资产重排**：筛选和网格/列表切换使用 layout animation，卡片位置连续移动。
11. **菜单与浮层**：淡入 + 4px 位移 + 0.98→1 缩放，时长 160ms。
12. **移动侧栏**：弹簧式滑入，遮罩同步淡入；关闭后焦点回到触发按钮。

约束：页面上同时存在的无限循环动画不超过 2 个；静止页面不持续消耗 GPU。

## 5. 页面改造方案

### 5.1 AppShell

- Logo 改为独立的 Oneiroi 梦境字标：抽象月相/镜头孔图形 + 文本，不复刻任何第三方标志。
- 顶栏由“整条硬边框”改成暖白半透明纸面，滚动后才出现轻阴影和更强 blur。
- 导航改为共享胶囊选中态；图标只在移动端或收窄时保留，桌面以文字为主。
- 服务状态放到账户菜单或小型状态点，减少顶栏噪音。
- 全局加入页面过渡容器、Toast、Tooltip 和命令入口占位。

### 5.2 灵感页

桌面采用 12 列编辑式布局：

- Hero 左侧为 Serif 标题和搜索，右侧放“首帧 → 尾帧”的重叠媒体样例。
- 背景使用极淡暖/冷径向光晕和点阵纸纹，不用高饱和渐变。
- 第一张模板为横跨 7–8 列的主推卡，其余模板形成 4–5 列辅助卡，避免三张完全相同。
- 卡片默认只显示图片、标题和简短元信息；Hover/键盘聚焦后显示“套用”操作。
- 分类栏吸附在内容顶部，滚动时保持可用；选中背景平滑移动。
- 搜索结果变化使用交叉淡入和布局重排；空状态保留搜索词并提供清除操作。

移动端：

- Hero 压缩到一屏约 45%，模板图片尽快进入首屏。
- 分类横向滚动并隐藏滚动条。
- 卡片操作不依赖 Hover，底部保留明确按钮。

### 5.3 生成页

核心改成“三层创作舞台”：

1. **左层：会话栏**
   - 宽度 248px，背景更接近纸张侧栏。
   - 会话项不再使用白卡；选中项用浅品牌底和 2px 标记。
   - 队列状态改成底部紧凑状态条。

2. **中层：镜头舞台**
   - 空状态不再是巨大文字空白，改成首尾帧双卡 + 中间轨迹的可视化舞台。
   - 上传后的图片直接进入舞台，支持替换、移除和轻量放大查看。
   - Agent 变成舞台顶部的命令条；展开后内容像 Notion block 向下生长。
   - 有任务后，舞台自然切换为任务时间线和结果，不进行页面跳变。

3. **底层：悬浮 Composer**
   - Composer 变为居中悬浮 Dock，默认只突出 Prompt 与生成按钮。
   - 首尾帧缩略图、规格和高级参数分为明确的上下两层。
   - 常用规格使用可点击 Chip；高级参数放在 Popover/Drawer，不继续撑高主卡。
   - 主按钮增加可用状态过渡；提交后从按钮自然转为短暂的任务状态反馈。

任务卡：

- 顶部改成 7 阶段细时间线，当前阶段自动滚动/高亮。
- 生成中显示双帧融合的低对比动态预览，而非纯进度条。
- 成功后媒体成为卡片主体，Prompt 和参数折叠为次级信息。
- 失败状态使用内联修复建议，不用整块红色警告框。

### 5.4 资产页

- 页面标题使用 Serif，上传按钮保持唯一主 CTA。
- 工具栏改为吸附式纸面栏：筛选、搜索、视图切换分组。
- 网格使用自适应列宽，视频/图片卡片根据比例保持不同高度，形成轻量作品墙。
- 操作按钮在桌面 Hover 后以玻璃浮层出现；移动端使用底部操作行。
- 打开资产时使用 Dialog 预览，支持左右浏览、复用和下载。
- 网格/列表和筛选结果使用共享布局动画。

## 6. 公共组件与文件调整

### 新增

```text
apps/web/src/components/motion/page-transition.tsx
apps/web/src/components/motion/reveal.tsx
apps/web/src/components/motion/layout-pill.tsx
apps/web/src/components/ui/tooltip.tsx
apps/web/src/components/ui/popover.tsx
apps/web/src/features/create/keyframe-stage.tsx
apps/web/src/features/create/job-timeline.tsx
apps/web/src/features/assets/asset-preview-dialog.tsx
apps/web/src/hooks/use-reduced-motion.ts
```

### 重点修改

```text
apps/web/src/styles.css
apps/web/src/components/layout/app-shell.tsx
apps/web/src/components/layout/workspace-sidebar.tsx
apps/web/src/features/inspiration/inspiration-page.tsx
apps/web/src/features/create/create-page.tsx
apps/web/src/features/create/agent-panel.tsx
apps/web/src/features/create/composer.tsx
apps/web/src/features/create/job-card.tsx
apps/web/src/features/assets/assets-page.tsx
```

原则：不改 Studio Store 和 BFF 契约，视觉重构不破坏已有功能与持久化数据。

## 7. 分阶段实施

### Phase A：设计底座

- 重建颜色、字体、间距、圆角、阴影和动效 token。
- 引入 Motion、Tooltip、Popover 与通用 Reveal。
- 建立 Notion 滚动条、焦点态、Skeleton 和 reduced-motion 规则。

验收：同一页面内不再出现互相冲突的圆角、阴影、蓝色和过渡时长。

### Phase B：壳层与导航

- 重做 Logo、顶栏、导航胶囊、账户菜单和页面切换。
- 重做会话侧栏及移动端开合。

验收：桌面/移动端导航顺滑，无布局跳动，键盘焦点正确。

### Phase C：灵感页

- 重做 Hero、主推模板、动态分类、搜索反馈和卡片操作层。
- 加入首屏 stagger 和滚动 reveal。

验收：首屏 1 秒内能识别“这是 AI 视频灵感入口”，移动端首屏能看到第一张模板。

### Phase D：生成页

- 新增 Keyframe Stage。
- 重做 Agent、Composer、高级参数和任务时间线。
- 加入提交、阶段推进、成功与失败过渡。

验收：首尾帧、Prompt、参数、提交和任务结果关系在视觉上连续，不像多个独立表单。

### Phase E：资产页

- 重做作品墙、吸附工具栏、预览 Dialog 和布局动画。

验收：筛选/切换无闪烁，图片优先，操作清晰。

### Phase F：QA、提交与部署

- Playwright 桌面 1440×1000、移动 393×852 截图回归。
- 检查 320px、768px、1024px、1440px 布局。
- 检查键盘导航、焦点、对比度和 reduced-motion。
- 执行 lint、typecheck、build、Python tests、E2E。
- 分阶段提交并推送，最后拉取到 `pi5`，重启 `oneiroi-studio.service`。

## 8. 验收标准

### 视觉

- 页面第一眼不再像后台管理系统。
- 暖白纸张、Serif 标题、Sans 工具和梦境紫形成稳定品牌识别。
- 同屏主要视觉焦点不超过 2 个。
- 卡片边框、阴影、圆角和留白符合统一 token。

### 动效

- 路由、导航、卡片、侧栏、Composer、任务和资产重排均有连续过渡。
- 无明显掉帧、内容闪现和布局跳动。
- reduced-motion 下所有功能可用且无持续动画。

### 功能

- 灵感套用、首尾帧上传、参数修改、生成、取消、重试、复用、资产上传/筛选/删除全部保持可用。
- 浏览器 mock 与 BFF 模式都能工作。
- 刷新后持久化数据不丢失。

### 性能

- 新增 JS gzip 尽量控制在 45KB 内。
- 图片不重复编码，不新增未经压缩的大图。
- 首屏动画不阻塞交互，动画只使用 compositor-friendly 属性。

## 9. 默认决策与待确认项

默认采用：

1. **暖白 Notion 基底 + 低饱和梦境紫品牌色**。
2. **Serif 只用于展示标题，正文与工具继续 Sans**。
3. **生成页改成首尾帧可视化舞台 + 悬浮 Composer**。
4. **引入 Motion for React，但不引入新的 UI 框架**。
5. **动效克制，优先连续性和状态反馈，不做高频粒子和大幅 3D 特效**。

确认本计划后，按 Phase A → F 实施；每个阶段保持可运行、可测试、可回滚。
