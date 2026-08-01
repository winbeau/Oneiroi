# Reusable resources

## `current-contracts/`

Oneiroi 当前 common package 的只读快照：GPU/session/profile、generation 和 Redis Runner protocol。用于设计 `gpu-server` HTTP contract 与迁移 diff。运行时代码仍以 `packages/python/common` 为权威，完成新 contract 后应更新或删除快照，避免长期漂移。

## `design-system/`

- `xju-feiyue-tokens.css`：MIT 仓库原始 token 快照。
- `motion.ts`：reduced-motion、IntersectionObserver 和 rAF/CSS variable 动效原语。

允许复用抽象 token、缓动、可访问性和 compositor-first 技术；必须删除飞跃分类/业务别名，不复制品牌内容、Mock 数据、演示页面和本地存储 token 方案。
