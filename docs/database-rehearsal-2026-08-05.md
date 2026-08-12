# 数据库升级演练报告（2026-08-05）

本报告记录 v1.3 基线向 `20260804_01` 学习者模型边界、`20260804_02` projection outbox 和 `20260804_03` schema alignment 的升级证据。正式生产升级仍需在发布窗口执行，不以本地演练替代生产变更审批。

## 默认 SQLite

- 运行库：`backend/data/study.db`
- 升级后备份：`backend/data/backups/study-pre-slice-close-20260805-085415.db`
- 备份 SHA256：`28AF023FD4950BE191389B57C097698653BC3E2AEB0937907B04CD0DD3221AB8`
- 当前运行库 SHA256：与备份一致（`28AF023FD4950BE191389B57C097698653BC3E2AEB0937907B04CD0DD3221AB8`）
- 数据量：`16 users / 0 concepts / 19 learning_events / 0 learner_evidence / 0 user_concept_state / 0 projection_outbox`
- schema marker：`20260804_01` 存在，Alembic head 为 `20260804_03`
- 完整性：`PRAGMA integrity_check = ok`；外键违规 `0`

由于默认 SQLite 没有概念，迁移不会凭空生成 legacy 证据或状态；历史事件如需建立学习者投影，必须显式调用按用户/概念/时间范围重放。

## PostgreSQL 16

演练容器：`mnemox-pg-rehearsal-20260805`，数据库从 v1.3 基线开始，按顺序执行：

```text
20260801_01 -> 20260804_01 -> 20260804_03
```

升级与恢复核对结果：

- 升级前：`2 users / 2 concepts / 2 learning_events`
- 升级后：`2 legacy evidence / 2 user_concept_state`
- legacy mastery/score：`72.5 / 0.725`、`41 / 0.41`
- 在线 outbox 消费：`1 processed`
- 用户、概念和学习事件外键均为 `ON DELETE CASCADE`
- `alembic check`：无新增操作

升级前 dump：`output/db-rehearsal/mnemox-pg16-pre-20260804-01-20260805.dump`

```text
SHA256 9E30989F9E385BA81593C15FB1585F1D0A9225CEC3E973971EA286F19F421421
```

该 dump 已恢复到新库，并再次核对 `revision=20260801_01`、`2/2/2` 的用户/概念/事件计数，证明回滚输入可恢复。

## 回滚预案

1. 在生产升级前创建 PostgreSQL 一致性快照或等价 `pg_dump`，记录 SHA256，并冻结应用写入窗口。
2. 升级失败或数据核对不通过时，停止新版本应用，保留失败日志和 outbox 状态。
3. 从升级前快照恢复到独立数据库，核对 revision、用户/概念/事件计数和外键，再切换应用连接。
4. 应用版本同步回退到与快照匹配的版本；不依赖自动 Alembic downgrade。
5. 恢复后重新执行 `alembic check`、关键数据量核对和按需 projection replay，确认事件与投影没有跨用户消费。

## 当前结论

数据库切片已收口。正式生产升级、常驻 outbox worker、失败队列监控和真实数据校准仍是后续发布工作；兼容周期结束前保留 `Concept.mastery`。
