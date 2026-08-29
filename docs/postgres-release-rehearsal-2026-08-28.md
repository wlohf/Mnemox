# PostgreSQL 发布演练报告（2026-08-28）

本报告记录当前代码 head `20260827_15` 的备份、历史升级和恢复验证。演练不会把“临时恢复库升级成功”写成“正式源库已升级”。

## 真实部署副本演练

- PostgreSQL：`16.15`（`server_version_num=160015`）。
- 源库 revision：`20260826_14`；public 表 `58` 张。
- custom-format dump：`mnemox-postgres-20260828T094715Z.dump`。
- SHA-256：`63b802a171d7b4571f065a56de06e1d83a78b520cbcad153cc2f1b6be8a070c2`。
- 恢复库：随机 `mnemox_restore_verify_*` 临时库；恢复前 archive list 与 SHA-256 均通过。
- 临时库通过生产入口升级 `20260826_14 -> 20260827_15`，随后 `alembic check` 返回无新增操作。
- `users/materials/notes/learning_events` 在升级前后均为 `0/0/0/0`，计数保持一致。
- 演练结束后临时库已自动删除；源库再次查询仍为 `20260826_14`。

由于当前源库没有业务行，这次真实副本演练证明的是 archive 可恢复、当前增量迁移可执行、schema 与 ORM 一致；不能单独证明非空生产数据保留。

## 非空历史数据演练

为覆盖上述空数据缺口，独立 PostgreSQL 16 临时实例从 `20260801_01` 创建历史 schema，写入固定用户、资料、笔记、概念和学习事件，执行 `pg_dump -Fc`、新库 `pg_restore`，再通过 `run_migrations.py` 升级到 `20260827_15`。验收结果：

- 五类历史行按固定主键和正文保留；
- `Concept.mastery=72.5` 生成 `score=0.725/reliability=0.35` 的 legacy evidence；
- `user_concept_state` 保留 `mastery_estimate=72.5/confidence=0.35`；
- 新账号安全字段默认值为 `token_version=0/failed_login_count=0`，两个时间字段为空；
- 当前 Coach、时态记忆、Outbox 与检索投影表存在；
- `alembic check` 无 schema drift。

同一流程已写入 `ci_postgres_upgrade_rehearsal.sh` 和 `test_postgres_upgrade_rehearsal.py`，后续迁移会重复执行，不再只测空库。

## 发布边界

正式源库升级尚未执行。发布窗口仍须冻结写入、停止旧后端、保留这组备份及校验文件、使用新镜像显式运行生产迁移入口，再完成健康检查与聚合数据核对。失败时从独立恢复库切换并同步回退应用版本，不运行自动 downgrade。
