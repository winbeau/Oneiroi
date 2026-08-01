# Oneiroi Refactor

该目录存放 Oneiroi 从内置 Gateway/Runner 算力实现迁移到独立 `xjuIcthub/gpu-server` 的计划与资源快照，不进入产品构建或 Python workspace。

- [`plan.md`](./plan.md)：身份、artifact、GPU API、Pi 部署和 GitHub transfer 的完整计划。
- [`resources/`](./resources/)：现有 contract 快照和 xju-feiyue 设计资源。

现有 Oneiroi 已有大量可复用实现，目标是抽取边界而非重写。
