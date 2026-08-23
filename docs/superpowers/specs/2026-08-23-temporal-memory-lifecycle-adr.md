# ADR：SQL 时态记忆冲突、事实替代与纠错闭环

- 日期：2026-08-23。
- 状态：当前有效。
- 上游决策：[学习智能底座架构决策](2026-08-03-learning-intelligence-foundation-architecture.md)。
- 后续执行顺序：[路线图](../../roadmap.md)。

## 1. 问题

此前 `MemoryDeclaration` 已记录审核、来源、有效时间和替代历史，但只按单条 `UserMemory.id` 判断前序声明。不同提炼来源能够针对同一个 `memory_key` 创建多个投影，从而出现两条同时生效的相反事实；同来源的待确认更新还可能直接覆盖已确认投影。另外，统一检索过滤了 `expires_at`，但部分聊天、Coach、Agent 和派生画像入口没有相同约束。

事实冲突属于规范数据问题，不能通过提示词、提高置信度或引入额外图数据库掩盖。当前规模下，SQLite/PostgreSQL 足以提供清晰、可审计且可迁移的事务边界。

## 2. 规范契约

`memory_declarations` 新增：

| 字段 | 含义 |
| --- | --- |
| `fact_key` | 当前用户下的稳定事实身份，来自 `UserMemory.memory_key`，不能用宽泛的 `category` 代替。 |
| `conflicts_with_id` | 待确认声明关联的、当前仍然生效的已确认声明。 |
| `resolution_reason` | 用户确认、拒绝、纠错、自动过期或历史重复清理的处理原因。 |

部分唯一索引 `uq_memory_declarations_user_fact_current` 对 `user_id + fact_key` 施加以下条件：

```sql
review_status = 'confirmed' AND valid_to IS NULL AND fact_key != ''
```

因此同一个用户、同一个事实在任意时刻最多只有一条已确认的开放声明。不同用户可以使用同名事实键；多个待审核候选和已经结束的历史不受该索引限制。

Alembic revision `20260823_12` 与 SQLite lightweight migration 均从已有 `UserMemory` 回填事实键。若旧库已经存在多个已确认声明，优先保留用户锁定的投影，其次保留最新观察；其他声明结束有效并记录 `migration_reconciled_duplicate_fact`，对应旧投影同步标记 `superseded`。

## 3. 生命周期与冲突策略

1. 人工声明或明确纠错会立即生效，并关闭同一事实下其他开放声明；用户事实自动锁定，后台抽取不得覆盖。
2. 不同来源产生与当前事实矛盾的新值时，新投影强制降为 `staged`，通过 `conflicts_with_id` 指向当前事实；旧投影仍为唯一可见事实。
3. 即使新候选来自原来源，只要它仍需审核，也必须保留当前投影，另建待确认候选，不能先把已确认值改成新值。
4. 用户接受候选后，旧声明变为 `superseded`，其 `valid_to` 与新声明的 `valid_from` 共用同一个审核时刻；旧投影退出产品检索。
5. 用户拒绝或标记不准确时，候选结束有效，原事实保持不变。
6. `expires_at` 到期时，投影和开放声明同步变为 `expired`；无论维护任务是否已运行，聊天、统一检索、Coach、Agent、笔记排序和学习快照均不得使用过期值。
7. 删除、替代、人工纠错和失效都会移除引用旧事实的 `agent_core_profile` 派生投影；删除声明时，先按用户清理其他声明中的替代或冲突引用。

所有写入均属于调用者现有 SQLAlchemy 事务，不启动第二套后台调度器，也不改变现有用户确认边界。

## 4. 用户入口

- `GET /api/memory/conflicts` 返回同一用户下仍待处理的事实对照。
- `GET /api/memory/memories/{id}/declarations` 按稳定事实键返回跨投影替代历史。
- `POST /api/memory/memories/{id}/correct` 要求纠错原因，并支持更新有效期。
- `POST /api/memory/expire` 执行当前用户的到期处理。
- 冲突确认和拒绝继续复用既有 `/api/agent/memory/candidates/{id}/confirm` 与 `/ignore` 审核边界。
- `/memory` 显示当前事实与新候选对照、确认/拒绝、有效截止、自动过期、人工原因和历史替代关系。

## 5. Graphiti 决策

当前 SQL 已覆盖事实唯一性、有效时间、跨来源冲突、审核、纠错、删除和用户隔离，因此不引入 Graphiti 运行时依赖。只有出现经过验证的跨会话时态关系查询缺口，且能够只投影筛选后的状态变化 episode、按用户删除、从 SQL 重建、在依赖不可用时降级时，才重新启动受控 Spike。

## 6. 验收

专项回归必须覆盖跨来源冲突、同来源待审核更新、用户确认替代、拒绝保留旧值、人工纠错原因、有效期结束、聊天/Agent/Coach 过期过滤、派生画像清理、删除引用处理、跨用户隔离，以及 SQLite/Alembic 历史回填和当前事实部分唯一索引。

本模块不创建新版 tag、GitHub Release 或安装资产。PostgreSQL 16、浏览器与 Windows 远程门禁需对本次提交重新运行；正式生产升级和真实 Electron 安装仍属于后续发布验收。
