# 更新记录：AgentRuntime 时区、免打扰与多实例调度加固

## 本周期目标

- 让 opt-in 复习积压 worker 在重启、跨时区、跨午夜、慢用户和多实例部署下保持可解释、可恢复。
- 保持“免打扰只延后触达、不丢任务、不自动写入”的产品边界。

## 已完成

### 1. 用户时区与本地日界线

- Coach 偏好新增经 IANA `ZoneInfo` 校验的 `time_zone`，设置页可选择当前设备与常用时区。
- 免打扰支持同日和跨午夜窗口；命中时直接把 `proactive_next_evaluate_at` 推进到本地结束点，不创建 AgentJob、Coach 事件或用户日志。
- 学习快照的“今天”任务完成、番茄钟和 Coach 每日上限使用用户本地日对应的 UTC 半开区间；调度时间 API 带 `Z`，避免浏览器把 UTC 当成本地时间。

### 2. 启动补偿、超时与安全重试

- `proactive_next_evaluate_at` 为空或已经到期的 opt-in 用户会在 worker 启动后的首轮正常补扫。
- 每个用户周期由 `AGENT_RUNTIME_USER_TIMEOUT_SECONDS` 约束；超时会取消并回滚正在运行的事务，再使用既有指数退避记录不含异常正文的安全重试。
- `/health` 与用户专属运行状态增加超时、免打扰延后和超时配置的最小化计数。

### 3. 多实例防重复

- PostgreSQL 用户偏好锁改为 `FOR UPDATE SKIP LOCKED`，另一实例遇到正在处理的用户时直接跳过，不排队重复执行。
- `(user_id, run_key)` 唯一约束继续作为第二道幂等保护。
- PostgreSQL 16 候选验收新增双 AgentRuntime worker 同时扫描同一到期用户、只产生一次任务和建议的断言；当前环境未配置真实 PostgreSQL，因此该项等待候选 workflow 执行。

## 数据变更与降级

- Alembic head 升至 `20260901_18`，为 `coach_preferences` 新增非空、默认 `UTC` 的 `time_zone`；SQLite lightweight migration 同步覆盖旧本地库。
- 缺少免打扰开始或结束时间时不延后；开始与结束相同视为零长度窗口。
- SQLite 仍不启动服务端定时 worker；页面内 Coach 保持可用。

## 验证结果

- Coach Kernel：`29 passed, 4 subtests passed`。
- 迁移链：`17 passed`，包含从空库升级至 `20260901_18` 与字段/索引断言。
- 前端生产构建：`npm run build` 通过。
- PostgreSQL 双 worker 验收代码已加入，真实执行仍依赖远程 PostgreSQL 16 候选环境。

## 后续事项

- 在候选 workflow 执行迁移、`SKIP LOCKED` 双 worker 和历史 dump/restore 验收。
- 下一模块进入干预效果自学习 v0：先做确定性归因与分桶，不引入 bandit 或自动写入。
