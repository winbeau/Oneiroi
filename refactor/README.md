# Oneiroi Refactor

该目录存放 Oneiroi 从内置 Gateway/Runner 算力实现迁移到独立 `xjuIcthub/gpu-server` 的计划与资源快照，不进入产品构建或 Python workspace。

- [`status.md`](./status.md)：当前产品决策和 Pi/H100 实机状态。
- [`production-launch.md`](./production-launch.md)：React 优先上线、身份、gpu-server 接入和三仓 E2E 的执行计划。
- [`START_PROMPT.md`](./START_PROMPT.md)：可直接交给 Oneiroi 编码 Agent 的启动提示词。
- [`plan.md`](./plan.md)：身份、artifact、GPU API、Pi 部署和 GitHub transfer 的长期重构计划。
- [`resources/`](./resources/)：现有 contract 快照和 xju-feiyue 设计资源。

现有 Oneiroi 已有大量可复用实现，目标是抽取边界而非重写。
