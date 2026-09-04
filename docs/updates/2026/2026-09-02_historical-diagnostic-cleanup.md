# 更新记录：历史诊断数据可回滚清理

## 本周期目标

- 清除安全错误边界启用前已经写入数据库的敏感错误片段。
- 默认只预览影响范围，只有显式 `--apply` 才提交，并让底层服务继续遵守调用方事务所有权。

## 已完成

### 1. 有界清理范围

- 新增 `diagnostic_maintenance_service`，只处理失败 Agent 任务的 `summary/result`、失败或重试日志的 `message/metadata`、projection outbox 与检索投影的 `last_error`。
- JSON 只检查 `error`、`error_summary`、`last_error`、`message`、`reason`、`summary` 等已知顶层诊断键；不递归扫描任务 payload、投影 payload 或用户业务正文。
- 已有 `error_code + error_summary` 被清理时同步重算只依赖安全内容的 `error_fingerprint`。
- 成功任务和成功日志不进入存量清理范围；现有在线写入/读取边界继续负责新数据防护。

### 2. 预览、事务与幂等

- `sanitize_persisted_diagnostics(..., dry_run=True)` 默认只返回各表的扫描行、变化行和变化列计数，不返回任何原始诊断内容。
- apply 模式按主键游标分页、逐页 flush，但不 commit；完整批次由调用入口统一提交或回滚。
- 重复执行对已经脱敏的数据报告零变化，不会不断改写 `[REDACTED]` 或指纹。
- `batch_size` 限制在 1–5000，用于控制每页 ORM/flush 工作集；整个 apply 仍保持单事务，便于失败时完整回滚。

### 3. 运维入口

在 `backend` 目录运行：

```bash
# 默认 dry-run，只输出聚合计数并回滚
venv/bin/python sanitize_diagnostics.py

# 核对统计后显式提交
venv/bin/python sanitize_diagnostics.py --apply --batch-size 500
```

命令输出不包含错误正文。正式环境应先保留数据库快照并执行 dry-run，再在低写入窗口运行 apply；新写入路径已经安全，在线并发写入不会成为完成本次存量清理的前置条件。

## 数据与兼容

- 不新增表、列或 Alembic 迁移，只原地更新现有诊断字段。
- 不改变 API 结构；读取边界的二次脱敏继续保留，作为历史清理之外的纵深防御。
- 服务不拥有 commit，既可由命令行原子提交，也可由测试或后续受控运维入口回滚。

## 验证结果

- `test_diagnostic_maintenance_service.py` 与 `test_error_safety.py`：`10 passed`。
- 覆盖 dry-run 零写入、apply 无内部 commit、调用方 rollback、分页、幂等、JSON 指纹更新，以及 payload/成功记录不被误改。
- 最终后端全量（Pydantic v2 目标弃用警告按错误处理）：`508 passed, 11 skipped, 58 subtests passed`。

## 已知限制 / 后续事项

- 本工具清理数据库内的已知诊断字段，不处理外部集中日志、备份或历史导出；这些介质仍需独立的保留期、访问控制和轮换策略。
- apply 是单事务，超大生产库应先通过 dry-run 评估行数，并在发布维护窗口执行与观察数据库负载。
