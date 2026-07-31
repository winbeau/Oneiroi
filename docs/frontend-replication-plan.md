# Oneiroi Studio 前端复刻与树莓派部署方案

> 目标：参考即梦 AI 首页的创作信息架构，保留 Oneiroi Studio 的独立品牌与视觉实现；使用现有 React + TypeScript 工具链，不复制第三方 Logo、文案、截图、插画或源代码。

## 1. 设计结论

参考页面当前可见的核心入口为：

```text
灵感      生成      资产

Agent 模式：自动 / 灵感搜索 / 创意设计
发现：短片 / 活动
```

适合 Oneiroi 的产品抽象是：

```text
灵感发现 → 低门槛创作 → 任务反馈 → 结果沉淀为资产 → 复用继续创作
```

Oneiroi 不做公开社区和商业化内容流；“发现、短片、活动”在内部版本替换为“团队灵感、项目模板、历史案例”。

## 2. 技术边界

### 2.1 继续使用的现有工具

| 领域 | 现有工具 | 用法 |
| --- | --- | --- |
| Web | Vite 7 + React 19 + TypeScript 5.9 | 本地开发和 Pi 上的静态预览 |
| 样式 | Tailwind CSS 4 + 当前 CSS 令牌 | Notion 式浅色、细边框、克制圆角 |
| UI 原语 | Radix UI Slot、现有 Button、lucide-react | 逐步补齐 Dialog、Select、Tabs、Tooltip、Progress |
| 状态 | Zustand | 工作区、草稿 Composer、会话侧栏和本地偏好 |
| 服务端状态 | TanStack Query | 资产、任务快照、SSE 后的缓存失效 |
| 表单校验 | 原生控件；后续按需加入 react-hook-form + zod | 上传、生成参数和高级设置抽屉 |
| Python API | FastAPI BFF/Gateway | 维持同源 `/v1` 边界，不让浏览器接触 Runner |

不引入新的 UI 框架、Next.js、Electron 或 ComfyUI 壳；不复制 `xju-feiyue` 的业务代码。`xju-feiyue` 仅作为本地视觉参考，并被根仓库忽略。

### 2.2 现有设计令牌

继续使用 `apps/web/src/styles.css` 中的令牌：

- 画布：白色和 `#F7F6F3` 柔和灰；
- 文字：`#37352F` / `#787774` / `#9B9A97`；
- 边框：`#EDECE9` / `#DCDAD4`；
- 交互蓝：`#2383E2`；
- 预览区可使用深色背景；
- 默认圆角 6/8/12 px，避免大面积渐变、玻璃拟态和厚重阴影。

## 3. 页面与组件方案

### 3.1 AppShell

顶部固定导航：

```text
Oneiroi Studio    灵感    生成    资产                         账户
```

- 当前入口用文字、细底线或弱底色表示；
- 不使用高饱和大色块导航；
- 移动宽度折叠会话栏，不在手机上强行保留三栏。

### 3.2 灵感页

一期展示私有模板和内部案例：

- 参考图/视频封面；
- 创作目标和动作摘要；
- 比例、质量、时长等标签；
- “套用到生成”直接把 Prompt、参考素材和规格带入 Composer；
- 后续可增加 Agent 入口：把一句想法整理成镜头描述和 Prompt。

### 3.3 生成页

桌面布局：

```text
┌──────────────┬──────────────────────────────────┐
│ 会话/项目栏   │ 会话标题、任务卡、视频结果流      │
│ 最近创作      │                                  │
│ 队列提示      │ 参考图 + Prompt + 生成参数        │
└──────────────┴──────────────────────────────────┘
```

Composer 默认只显示：

```text
上传参考图 · Prompt · I2V · 快速/高质量 · 比例 · 分辨率 · 时长 · 提交
```

高级抽屉再显示：

- 首帧/尾帧；
- 首尾帧强度；
- Seed；
- Prompt 增强；
- 负面提示词；
- GPU 队列；
- Offload/量化等管理员参数。

任务卡必须显示阶段，而不是只显示转圈：

```text
draft → uploaded → queued → assigned → preparing → generating → encoding → succeeded
```

失败时显示可读原因、`job_id` 和重试/复用参数操作。

### 3.4 资产页

支持列表/网格切换，默认信息优先：

- 参考图片；
- 生成视频；
- 收藏模板；
- 创建时间、归属会话、规格；
- 预览、下载、删除；
- “复用本次设置”回到生成页。

### 3.5 Agent 模式

不在第一轮复制成复杂聊天机器人。分三步实现：

1. **Prompt 整理**：把用户短句改成镜头、动作、光线、声音结构；
2. **灵感搜索**：只搜索内部模板和用户资产，不抓取公开第三方内容；
3. **创意设计**：生成镜头方案、首尾帧建议和质量档位。

Agent 输出必须能被用户编辑和确认，不直接无提示提交长时间推理任务。

## 4. 实施分期

### P0：当前骨架整理

- 保留顶部“灵感 / 生成 / 资产”；
- 把真实 `assets/head.png`、`assets/tail.png` 接入灵感模板缩略图；
- Composer 完成上传预览、Prompt、质量、比例、时长选择；
- 增加空态、加载态、失败态和成功视频卡；
- 不接真实推理 API，先用本地 mock 数据验证交互。

### P1：生成闭环

- `POST /v1/assets` 上传；
- `POST /v1/jobs/i2v` 创建任务；
- `GET /v1/jobs/{id}` 查询；
- `GET /v1/jobs/{id}/events` 接收 SSE；
- 任务卡显示 `preparing / generating / encoding`；
- 成功后加入资产页。

### P2：参数和资产复用

- 首帧/尾帧选择；
- 快速/高质量队列；
- 720p/1080p、时长、Seed；
- 复用参数、重新生成、下载；
- 用户隔离和错误详情。

### P3：Agent 与灵感

- Prompt 结构化；
- 内部模板搜索；
- 镜头设计卡；
- 用户确认后提交任务。

### P4：细节和可访问性

- 键盘导航和焦点态；
- reduced-motion；
- 移动端 Composer 抽屉；
- 任务状态不能只依赖颜色；
- Playwright 核心路径测试。

## 5. 本地开发

```bash
pnpm install
pnpm dev
```

本地默认：

```text
WebUI: http://127.0.0.1:5173
BFF:   http://127.0.0.1:8000
```

质量检查：

```bash
pnpm check
uv run ruff check .
uv run pytest
```

工作区 Git 流程：

```bash
git pull --ff-only origin main
# 修改、检查
git add <明确的文件>
git commit -m "feat: ..."
git push origin main
```

不提交：`.env`、`.data/`、模型权重、生成视频、`LTX-2/` 官方源码克隆、`xju-feiyue/` 参考克隆和 `.beaupi/` 会话状态。

## 6. 树莓派工作区部署

树莓派只负责 WebUI，不承担模型推理。部署脚本为：

```bash
scripts/deploy-web-pi.sh
```

脚本执行：

1. 检查工作区没有已跟踪的未提交改动；
2. `git fetch` + `git pull --ff-only origin main`；
3. `pnpm install --frozen-lockfile`；
4. 构建 Vite 静态产物；
5. 用 `--host 0.0.0.0` 监听工作区内网。

生产式预览模式：

```bash
scripts/deploy-web-pi.sh --mode preview --host 0.0.0.0 --port 4173
```

本地热更新模式：

```bash
scripts/deploy-web-pi.sh --mode dev --host 0.0.0.0 --port 5173
```

访问地址：

```text
http://<树莓派工作区内网IP>:4173
```

若通过 SSH 隧道访问：

```bash
ssh -L 4173:127.0.0.1:4173 <pi-host>
```

然后打开 `http://127.0.0.1:4173`。

### 建议的长期运行方式

部署脚本本身保持前台运行，交给 systemd 或 tmux 管理；不把 `nohup` 逻辑硬编码进应用：

```bash
tmux new -s oneiroi-web
scripts/deploy-web-pi.sh --mode preview --host 0.0.0.0 --port 4173
```

后续更新只需：

```bash
git pull --ff-only origin main
scripts/deploy-web-pi.sh --mode preview --host 0.0.0.0 --port 4173
```

## 7. 验收标准

- 工作区内网设备可打开树莓派地址；
- 刷新、深链接和静态资源正常；
- 灵感 → 生成 → 资产导航闭环可用；
- 上传参考图后能看到预览和参数；
- mock 任务可看到完整阶段状态；
- 真实 API 接入后浏览器只访问同源 BFF，不直接访问 H100 Runner；
- Pi 不保存模型权重和大视频，只承担 Web 入口/静态前端职责。

## 8. 版权与复刻边界

参考即梦 AI 的信息架构和任务流，不复制其品牌、Logo、图标、截图、具体文案、插画、页面源代码或受保护素材。参考 `xju-feiyue` 只限视觉系统和组件组织方法；如未来复用其 MIT 代码，单独保留版权和许可证声明。
