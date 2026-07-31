# LTX-2.3 在 H100 上的推理启动计划

> 目标：以最少变量、最短路径，在 H100 的单张 GPU 上完成一条可复现的 LTX-2.3 图生视频（I2V）推理；验证后再接入 Oneiroi Runner。
>
> 更新：固定 GPU 0–3 / 固定 2 Fast + 2 HQ 的早期设想已由动态空闲卡、显式热加载/释放方案取代，见 [`ltx-desktop-inspired-backend-plan.md`](./ltx-desktop-inspired-backend-plan.md)。

## 1. 结论先行

最快路径不是先搭 ComfyUI、LTX Desktop、Gateway 或四卡调度，而是：

1. 通过 `h100-server` 登录 H100；
2. 核验 GPU、驱动、磁盘和网络；
3. 在独立非 root 工作目录克隆官方 `Lightricks/LTX-2`；
4. 使用官方 Python pipeline 和 LTX-2.3 22B Distilled checkpoint；
5. 固定 `CUDA_VISIBLE_DEVICES=0` 跑最小 I2V smoke test；
6. 保存命令、Git commit、模型 revision、输入、seed、日志和输出；
7. 再跑目标规格基准；
8. 最后封装到 `workers/runner`，复制到 GPU 0–3。

首条结果阶段只用一张 H100。不要在基线成功前引入多 GPU、服务化、量化、`torch.compile`、自定义 attention kernel 或四卡队列。

## 2. 与 Oneiroi 总体计划的对应关系

本计划对应项目开题计划的 P0 和 P1 前半段：

- P0：H100 完成官方 LTX-2.3 I2V 基准任务；
- P1：把已验证的单卡命令封装为一个受控 Fast Runner；
- 后续资源划分由热加载时的 GPU inventory 决定，不假设连续 index：
  - 默认请求最多 4 张真实空闲 H100；
  - 4 卡：2 Fast + 2 HQ；
  - 3 卡：2 Fast + 1 HQ；
  - 2 卡：1 Fast + 1 HQ；
  - 1 卡：仅 Fast，HQ 禁用。

## 3. 启动策略

### 3.1 第一优先：Distilled 单卡 I2V

选择官方 LTX-2 Python pipeline，而不是先使用桌面壳或 ComfyUI：

- 依赖链更短；
- 参数、日志和输出路径更容易固定；
- 更适合后续封装为后台 Runner；
- 出错时可以直接区分驱动、PyTorch、权重、输入参数和显存问题。

首选 checkpoint 以官方仓库当前 README/模型卡为准。当前官方入口包含：

```text
Lightricks/LTX-2
Lightricks/LTX-2.3
ltx-2.3-22b-distilled-1.1.safetensors
ltx_pipelines.distilled
```

空间上采样器、文本编码器及其他配套文件不得凭经验混配；执行时按固定 Git commit 对应的 README 和 `--help` 选择，并记录 Hugging Face revision。

### 3.2 第二优先：目标规格基准

Smoke test 成功后再测试项目实际需要的 I2V 规格。建议依次增加：

1. 官方最小受支持规格，短视频；
2. 768×512 附近的横屏短视频；
3. 一期 WebUI 默认规格；
4. 更长时长；
5. 两阶段 HQ。

一次只改变一个变量，避免同时改变分辨率、帧数、步数、精度和 upscaler。

### 3.3 第三优先：服务化与多卡

只有原始官方命令稳定后，才将调用封装到 Oneiroi Runner。四张卡按四个单卡进程部署，不先把多张卡拼成一个任务。

## 4. 前置条件

### 4.1 访问条件

本机已经通过 `ProxyJump pi5` 建立到 `10.30.176.95` 的路由。当前 `h100-server` 配置使用 `root`，正式执行前应改为服务器上已有的专用非 root 推理用户：

```sshconfig
Host h100-server
    HostName 10.30.176.95
    User <非 root 推理用户>
    ProxyJump pi5
```

系统级驱动或账户调整由服务器管理员单独完成，推理部署和运行脚本不使用 `sudo`。

### 4.2 H100 环境最低检查项

进入服务器后先收集：

```bash
hostname
id
nvidia-smi
nvidia-smi -L
nvidia-smi --query-gpu=index,name,memory.total,memory.used,utilization.gpu,temperature.gpu,ecc.errors.uncorrected.volatile.total --format=csv
python3 --version
git --version
df -hT
free -h
```

通过标准：

- 至少一张空闲 H100 可用于 GPU 0；
- NVIDIA 驱动工作正常，无持续 ECC/Xid 异常；
- GPU 0 没有未知生产任务；
- 模型盘建议预留至少 150 GB，若同时保留 Distilled、Dev/HQ 和 Hugging Face cache，建议预留 200 GB 以上；
- 输出盘另行预留空间，避免模型 cache 和生成视频挤满系统盘；
- 能访问 GitHub 与 Hugging Face，或已经准备实验室内部镜像；
- 已阅读并接受对应模型许可；若模型仓库要求授权，由操作者本人执行 `hf auth login`，不在日志或脚本中保存 token。

## 5. 目录布局

优先选 H100 本地高速数据盘上的可写路径；实际根目录在核验 `df` 后确定。建议布局：

```text
$LTX_ROOT/
├── src/LTX-2/                 # 固定 Git commit 的官方仓库
├── models/LTX-2.3/            # 固定 revision 的模型文件
├── cache/huggingface/         # 独立 HF cache
├── inputs/                    # 测试参考图
├── outputs/smoke/             # 最小测试输出
├── outputs/benchmarks/        # 基准输出
├── logs/                      # 完整 stdout/stderr 和监控数据
└── manifests/                 # 每次推理的参数与版本记录
```

建议环境变量：

```bash
export LTX_ROOT=/data/oneiroi/ltx-2.3   # 以实际可写高速盘为准
export HF_HOME="$LTX_ROOT/cache/huggingface"
export HF_HUB_ENABLE_HF_TRANSFER=1
export PYTHONUNBUFFERED=1
```

不要把模型、输入素材或输出放进 Oneiroi Git 仓库。

## 6. 分阶段执行计划

### 阶段 A：只读环境核验（约 10 分钟）

操作：

1. 登录 `h100-server`；
2. 记录主机、用户、OS、内核；
3. 记录 8 张 GPU 的型号、显存、占用、温度和错误状态；
4. 确认 GPU 0 是否空闲；
5. 找到容量足够的本地高速盘；
6. 检查 Python、Git、`uv`、`ffmpeg`/`ffprobe`；
7. 检查 GitHub/Hugging Face 可达性。

产物：`logs/environment.txt`。

停止条件：

- GPU 0 有不能中断的任务；
- 驱动无法识别 GPU；
- 有 Xid/ECC 硬件异常；
- 找不到足够的可写磁盘；
- 模型许可尚未确认；
- 只能使用系统 Python 且无法创建隔离环境。

### 阶段 B：创建隔离运行环境（约 10–20 分钟）

原则：优先使用官方仓库要求的 `uv` 环境，不污染系统 Python。

命令骨架：

```bash
mkdir -p "$LTX_ROOT"/{src,models,cache,inputs,outputs/smoke,outputs/benchmarks,logs,manifests}
cd "$LTX_ROOT/src"
git clone https://github.com/Lightricks/LTX-2.git
cd LTX-2
git rev-parse HEAD
```

接着完整阅读当前 checkout 的 README/安装说明，再执行它要求的 `uv sync`。不要在没有核对 lockfile 和 Python 要求时自行混用 `pip`、Conda 和系统包。

版本记录：

```bash
git rev-parse HEAD > "$LTX_ROOT/manifests/ltx2-git-commit.txt"
```

### 阶段 C：下载并校验模型（耗时取决于带宽）

操作：

1. 固定 Hugging Face 模型 revision；
2. 先下载 Distilled 首跑必需文件；
3. 暂不下载 LoRA、训练文件和 HQ 非必需权重；
4. 下载后记录文件名、大小和 SHA256；
5. 确认文件不是 Git LFS pointer 或损坏的部分文件。

下载命令按官方模型卡生成，形式如下：

```bash
hf download Lightricks/LTX-2.3 \
  <官方 README 对应的 Distilled 和配套文件> \
  --revision <固定 revision> \
  --local-dir "$LTX_ROOT/models/LTX-2.3"
```

校验：

```bash
find "$LTX_ROOT/models/LTX-2.3" -type f -print0 \
  | sort -z \
  | xargs -0 sha256sum \
  > "$LTX_ROOT/manifests/ltx-2.3-sha256.txt"
```

### 阶段 D：确认官方 CLI 参数（约 5 分钟）

先查看帮助而不是直接猜参数：

```bash
cd "$LTX_ROOT/src/LTX-2"
uv run python -m ltx_pipelines.distilled --help \
  | tee "$LTX_ROOT/logs/distilled-help.txt"
```

从当前 commit 的 README 和 `--help` 确认：

- checkpoint 参数名；
- image conditioning 参数名；
- prompt 参数名或配置文件格式；
- width、height、帧数/FPS 的合法约束；
- seed；
- spatial upsampler 是否为首跑必需；
- 输出目录/文件参数；
- attention backend 和精度的默认值。

只有这里确认后，才写最终 smoke 命令。

### 阶段 E：GPU 0 最小 I2V smoke test（约 5–20 分钟）

固定单卡：

```bash
export CUDA_VISIBLE_DEVICES=0
```

运行策略：

- 使用一张已知可正常解码的 RGB JPG/PNG；
- 使用简单、明确、低歧义的 prompt；
- 采用官方示例中最小或推荐的合法分辨率、帧数和步数；
- 固定 seed；
- 输出到唯一任务目录；
- 用 `/usr/bin/time -v` 记录墙钟时间和主机内存；
- 同时用 `nvidia-smi` 采样显存、GPU 利用率、功耗和温度。

命令骨架：

```bash
run_id="smoke-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$LTX_ROOT/outputs/smoke/$run_id"

CUDA_VISIBLE_DEVICES=0 /usr/bin/time -v \
  uv run python -m ltx_pipelines.distilled \
  <以当前 --help 为准的 I2V 参数> \
  2>&1 | tee "$LTX_ROOT/logs/$run_id.log"
```

旁路监控：

```bash
nvidia-smi dmon -i 0 -s pucvmet -d 1 \
  > "$LTX_ROOT/logs/$run_id-gpu.csv"
```

完成后：

```bash
ffprobe -v error -show_format -show_streams <输出视频>
```

Smoke test 验收：

- 进程退出码为 0；
- 生成可由 `ffprobe` 解码的视频；
- 输出不是 0 字节；
- 日志中没有 CUDA OOM、NaN、Xid 或持续 decode error；
- 峰值显存保留至少约 5–8 GB 安全余量，或明确记录为何接近上限；
- manifest 可还原模型、代码、输入、prompt、seed 和全部参数。

### 阶段 F：目标规格基准（约 30–90 分钟）

基准矩阵控制在 3–5 条任务，不做大规模扫参：

| 编号 | 管线 | 规格 | 目的 |
| --- | --- | --- | --- |
| B0 | Distilled I2V | smoke 规格 | 可用性基线 |
| B1 | Distilled I2V | 一期默认横屏规格 | 默认快速档耗时/显存 |
| B2 | Distilled I2V | 一期默认竖屏规格 | 纵向输入验证 |
| B3 | Distilled I2V | 较长时长 | 帧数扩展与 OOM 边界 |
| B4 | 两阶段 HQ I2V | 一期 HQ 规格 | HQ 耗时/显存/质量 |

每条记录：

- Git commit 和模型 revision/SHA256；
- GPU 型号及编号；
- 输入图 SHA256；
- prompt/negative prompt；
- seed；
- 分辨率、帧数、FPS、步数和精度；
- 冷启动时间、模型加载时间、推理时间、编码时间、总时间；
- 峰值 GPU 显存、主机内存、平均 GPU 利用率；
- 输出文件大小和 `ffprobe` 摘要；
- 主观问题，如闪烁、身份漂移、文字伪影和首帧偏移。

### 阶段 G：封装 Oneiroi Fast Runner

只有 B0/B1 稳定后进行：

1. 在 `workers/runner` 增加真实 LTX adapter；
2. 进程启动时加载模型一次，任务间复用模型；
3. Runner 只接受受控参数对象，不接受客户端服务器路径；
4. 输入复制到任务专属目录；
5. 输出写入任务专属目录；
6. 逐阶段报告 `preparing → generating → encoding`；
7. 捕获 OOM、输入错误、模型加载失败和编码失败；
8. 先在一张动态选出的空闲 GPU 上完成 Fast Model Worker，稳定后扩展到 1–4 张卡；
9. HQ adapter 使用独立 profile/Model Worker，不在任务间与 Fast pipeline 原地交换；实际物理 GPU 由 Gateway 租约决定。

Runner 启动边界：

```bash
CUDA_VISIBLE_DEVICES=0 \
ONEIROI_RUNNER_NAME=fast-0 \
ONEIROI_RUNNER_QUEUE=fast \
ONEIROI_RUNNER_GPU_DEVICE=0 \
uv run oneiroi-runner
```

现有 Runner 仍是生命周期骨架，因此不能把“进程启动”误判为“LTX 推理已接通”。

## 7. 加速顺序

基线成功后，按以下顺序优化，每次只改一项并与 B1 对比：

1. 模型常驻，消除每任务重复加载；
2. 使用官方推荐的 H100 attention backend；
3. 固定 dtype，并确认没有意外 FP32 路径；
4. 开启官方明确支持的编译/缓存选项；
5. 优化视频编码线程和临时目录；
6. 再评估量化；
7. 最后评估单任务多 GPU。

对于两位内部用户，优先增加独立单卡 Worker 吞吐，而不是让一个普通任务占多张 H100。

## 8. 故障处理与停止条件

### CUDA OOM

处理顺序：

1. 保存完整日志和参数；
2. 确认 GPU 上没有其他进程；
3. 降低帧数；
4. 再降低分辨率；
5. 核对官方 dtype/attention 配置；
6. 不在首轮直接引入未知量化补丁。

### 权重或配套文件不匹配

- 停止运行；
- 对照固定 commit 的 README；
- 核对模型 revision、文件名、SHA256 和 upscaler 版本；
- 不混用 LTX-2、LTX-2.3、旧版 LTX-Video 的组件。

### 下载失败

- 保留可续传 cache；
- 检查磁盘 inode 和剩余空间；
- 需要授权时由操作者本人登录 Hugging Face；
- 不把 token 写进 shell history、仓库、日志或 systemd unit。

### GPU/驱动异常

出现 Xid、持续 ECC 错误、GPU 掉卡或 `nvidia-smi` 失败时立即停止，把诊断交给服务器管理员；不要用重启推理进程掩盖硬件或驱动故障。

## 9. 最终验收标准

P0 完成需要同时满足：

- GPU 0 上完成至少一条官方 LTX-2.3 Distilled I2V；
- 输出 MP4 可播放且 `ffprobe` 校验通过；
- 有完整日志、GPU 监控和 manifest；
- 相同环境、输入和 seed 可重复运行；
- 记录默认规格的总耗时和峰值显存；
- 明确 HQ 是否能在单张 H100 上运行及其资源数据；
- 没有改动系统 Python、系统 CUDA 或其他用户环境；
- 模型与代码版本已固定；
- 模型许可已确认。

P1 单卡原型完成还需要：

- `fast-0` 常驻加载模型；
- 能从受控任务目录读取输入并写出结果；
- 能报告准备、生成、编码、成功/失败状态；
- 连续执行至少 3 条任务无结果串目录、无持续显存增长；
- Runner 退出后不影响其他 GPU。

## 10. 预计时间

在驱动正常、GPU 空闲、模型可直接下载的前提下：

| 工作 | 预计时间 |
| --- | ---: |
| 环境核验 | 10 分钟 |
| 创建隔离环境 | 10–20 分钟 |
| 模型下载 | 取决于带宽，通常是最大变量 |
| CLI 参数确认 | 5 分钟 |
| 首条 smoke test | 5–20 分钟 |
| 默认规格基准 | 30–60 分钟 |
| HQ 首测 | 30–90 分钟 |
| Fast Runner 最小封装 | 0.5–1 天 |

不计算模型下载时，目标是在约 30–60 分钟内得到第一条可验证视频。

## 11. 执行时的第一批命令

获得 H100 普通用户连接后，第一轮只执行只读核验：

```bash
ssh h100-server
hostname
id
nvidia-smi -L
nvidia-smi
python3 --version
git --version
uv --version || true
ffmpeg -version || true
df -hT
free -h
```

核验结果通过后，再决定实际数据盘路径、Python 版本、模型 revision 和最终 smoke 命令。

## 12. 参考

- 官方推理仓库：<https://github.com/Lightricks/LTX-2>
- 官方 LTX-2.3 模型仓库：<https://huggingface.co/Lightricks/LTX-2.3>
- 项目总计划：[`../Oneiroi-Studio-开题计划.md`](../Oneiroi-Studio-开题计划.md)
- 当前 Runner 说明：[`development.md`](./development.md)
