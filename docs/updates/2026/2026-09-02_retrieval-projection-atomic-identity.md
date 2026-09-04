# 更新记录：检索投影原子身份创建

## 本周期目标

- 消除同一用户、同一资料、同一后端首次建立检索投影时的“先查后插”竞争。
- 保持既有 SQL manifest、向量索引和失败恢复状态不变。

## 已完成

- `_ensure_projection` 在 PostgreSQL 使用唯一约束名、在 SQLite 使用唯一字段组执行 `INSERT ... ON CONFLICT DO NOTHING`。
- 无论本次请求创建还是复用投影，随后都按 `(user_id, source_type, source_id, backend)` 重新读取唯一行；数据库唯一约束成为投影身份的最终仲裁者。
- 不支持原生分支的未声明方言保留显式兼容路径，不会被误标为已经具备并发保证。

## 数据与兼容

- 不新增 schema 或迁移；复用 `uq_retrieval_projection_source_backend`。
- 不改变 `source_version`、`attempt_count`、状态机或提交检查点；重复强制索引仍增加尝试次数，但不会增加投影身份行。

## 验证结果

- 检索投影生命周期专项为 `12 passed`。
- 新增 SQL 捕获验证 SQLite 的每次身份确保都实际发出 `ON CONFLICT DO NOTHING`，重复强制索引后投影计数仍为 1。

## 后续事项

- 原子身份只解决首次插入竞争；长耗时向量调用的先后顺序仍需独立 fencing。本轮下一模块将对同用户检索变更串行化，并在取得锁后重新加载规范资料。
