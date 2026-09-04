# 更新记录：结构化安全诊断

## 本周期目标

- 在已脱敏、限长的错误摘要上增加稳定类别和可关联指纹。
- 让任务、投影与 worker 的同类失败可以聚合定位，而不需要在 API 或持久状态中暴露原始异常正文。

## 已完成

### 1. 共享诊断契约

- 新增 `SafeErrorDiagnostic`，固定包含调用方定义的 `error_code`、脱敏单行 `error_summary` 和 16 位 `error_fingerprint`。
- 错误码只由业务调用点提供并规范化，不从异常正文猜测；指纹只对“稳定错误码 + 已脱敏摘要”计算 SHA-256 截断值，原始密钥不参与散列。
- 修复已有 `[REDACTED]` 占位符的二次脱敏幂等性；同一安全摘要经过写入和读取边界后不再不断增加右括号，也不会改变指纹。

### 2. 关键链路接入

- 同步 Agent 执行失败会把 `agent.execution_failed`、安全摘要和指纹写入任务结果；历史失败任务在读取时也会从已脱敏摘要生成固定类别与指纹。
- 检索投影按 `retrieval.index_failed`、`retrieval.forget_failed`、`retrieval.degraded` 分类，保留原有用户可读说明并增加关联指纹。
- projection outbox 内部序列化和用户 DLQ 列表增加 `projection_outbox.processing_failed` 与指纹；DLQ 仍不返回 payload 或异常正文。
- RAG 状态使用 `rag.operation_failed`；AgentRuntime 与 outbox worker 健康状态保留无正文的错误码和指纹，公开健康接口仍移除 `last_error`。

## 数据与兼容

- 不新增数据库列或迁移；结构化字段由现有安全摘要派生，新任务额外把诊断对象写入已有 JSON result。
- 现有 `last_error`、`summary` 和前端读取字段保持兼容，新增字段为向后兼容扩展。
- 指纹用于同类诊断关联，不是全局事件 ID，也不得用于还原或替代服务端受控日志。

## 验证结果

- 结构化诊断核心专项当前为 `48 passed`；更大的事务、检索、outbox、worker、RAG 和 Coach 组合专项先前为 `107 passed, 4 subtests passed`，其中发现的唯一占位符幂等问题已经修复。
- 覆盖错误码规范化、摘要脱敏、指纹稳定性、历史 Agent 读取、Agent 持久失败、检索 ingest/forget、DLQ、RAG 和 worker 健康输出。
- 本轮最终后端全量为 `497 passed, 10 skipped, 58 subtests passed`。

## 已知限制 / 后续事项

- 当前错误码覆盖关键任务与投影链路，尚未形成所有 HTTP 领域错误的统一目录；扩展时应优先按可采取的恢复动作分类，避免直接复制异常类名。
- 后续模块已提供默认 dry-run、显式 apply、调用方事务和幂等分页的历史诊断清理入口；读取边界仍继续二次脱敏。外部日志、备份与导出的保留治理仍需单独收口。
