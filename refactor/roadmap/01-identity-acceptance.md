# 阶段 1：真实 Authentik 双用户验收

## 目标

把现有“Access challenge + 测试 JWT + 双 owner 后端隔离”提升为两个真实邀请用户的浏览器端验收。

## 当前已有

- Cloudflare Access application、issuer、audience 和 Authentik login method 已配置。
- BFF 已验证 Access JWT，并从 `(issuer, subject)` 生成稳定 owner。
- 伪造 `oneiroi_user` cookie、`X-Oneiroi-User` 或缺失 JWT 均无效。
- 服务断言和后端 owner 过滤已有单测与实机双 owner 证据。

## 仍缺

- 两个真实邀请用户的浏览器 session。
- 无权限用户的 group policy 拒绝证据。
- 登录、退出、会话过期、重新登录后的 owner 稳定性。
- conversation、asset、job、文件和 SSE 的真实双用户交叉访问矩阵。

## 执行步骤

### 1. 准备测试身份

- 用户 A：允许访问的 Authentik group。
- 用户 B：允许访问的 Authentik group。
- 用户 C：不在允许 group，或临时移出 group。
- 使用隔离浏览器 profile，禁止共享 Access cookie。

不得收集、复制或提交 Access cookie、JWT、密码和完整邮箱信息。

### 2. 验证 Access 行为

对 A/B/C 分别验证：

- `/`
- `/create?from=identity-acceptance`
- `/v1/conversations`
- 任意 conversation 深链接

验收：

- A/B 登录后回到原 path/query。
- C 无法进入应用和 API。
- 退出或 session 过期后 API 不再可用。
- 直接访问 Pi/H100 私有端口不能绕过 Access/服务身份。

### 3. 验证 owner 稳定性

A/B 分别：

1. 第一次登录并创建 conversation。
2. 退出后重新登录。
3. 换一个浏览器 profile 再登录。
4. 验证仍能看到自己的记录，且 owner 不发生漂移。

证据中只记录 owner 的短哈希或测试标签，不记录完整 subject/token。

### 4. 双用户隔离矩阵

A/B 各自创建：

- conversation；
- image asset；
- compute session；
- job；
- job event stream；
- 成功时的 MP4/manifest，或明确失败记录。

双向交叉验证：

| 资源 | 期望 |
| --- | --- |
| list | 不出现对方资源 |
| get by ID | 404 |
| asset/job file | 404 |
| manifest | 404 |
| SSE events | 404 或连接拒绝 |
| cancel/retry/release | 404，且不改变对方状态 |

### 5. 验收记录

更新 `refactor/production-launch.md`：

- 测试日期、release SHA、浏览器/profile 标签。
- 每类资源的状态码和隔离结果。
- group 拒绝、退出、过期和深链接回跳结果。
- 回滚方法和未通过项。

## 完成门

- A/B owner 稳定且不同。
- 所有交叉访问均不可见或 404。
- C 无法访问应用/API。
- 伪造 cookie/header 无效。
- 证据明确来自真实 Authentik/Access session。

## 停止条件

若 Authentik subject 因登录方式或身份合并而变化，立即停止 gpu-server 放量。先设计持久化 identity mapping 和 owner 迁移，不得继续生成新的哈希 owner 导致数据分裂。

## 预计时间

0.5–1.5 天，受邀请、邮箱验证、group propagation 和 Access session 缓存影响，约 ±40%。
