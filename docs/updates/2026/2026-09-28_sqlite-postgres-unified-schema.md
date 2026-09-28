# SQLite 与 PostgreSQL 统一迁移与方言收拢

定位确认：源码公开版与桌面版默认 SQLite，托管线上服务使用 PostgreSQL，两者都保留。本次目标不是二选一，而是降低同时维护两个数据库的成本：一套迁移、一处方言差异。

## 修改

### 1. SQLite 改用同一条 Alembic 迁移链

- 实测全部 33 个 revision 可在空 SQLite 文件上升级到 head，`alembic check` 无差异，因此历史迁移无需改写。
- `init_db` 在 SQLite 上改为启动时执行 Alembic 升级（桌面版和源码自部署没有独立迁移步骤）；PostgreSQL 行为不变，仍由 `run_migrations.py` 在 advisory lock 下迁移，应用启动只校验版本。
- 尚未纳入 Alembic 的旧 SQLite 文件只处理一次：用 Alembic 构建的基线 `20260928_31` DDL 创建缺失表 → 执行冻结的 `_run_lightweight_migrations` 补齐列、索引和历史回填 → 补建旧手写迁移遗漏的 `ix_notes_source_path`、`ix_wrong_questions_concept_id` → `stamp` 基线 → `upgrade head`。缺失表按基线 DDL 创建而不是按当前模型，保证以后新增的 revision 仍能在旧文件上执行。
- 实测 v1.3 形态的旧文件补齐后与 head 仅差：`REAL`/`FLOAT` 写法（SQLite 同一存储类型）和 `wrong_questions.concept_id` 外键（SQLite 需重建表才能添加，按已知差异保留）。
- `alembic/env.py`：进程内调用时不再用 `alembic.ini` 重置应用日志；SQLite 自动生成使用 batch 操作；运行时创建的稀疏检索表不参与比对，防止自动生成误删。
- 桌面打包脚本增加 `alembic/`、`alembic.ini` 与 `alembic` 子模块。

### 2. 方言差异收拢到 `app/utils/dialect.py`

- 新增 `dialect_name`、`is_postgresql`、`conflict_insert`。原先在 8 个文件里分别 `import` PostgreSQL / SQLite `insert` 并写两遍的 `ON CONFLICT` 语句统一为一处；冲突目标统一用列（PostgreSQL 据此匹配同列唯一约束）。
- 删除只为“其他数据库”保留、实际不会执行的逐条回退写法（资料投影、画像、知识来源、知识投影 outbox、学习者投影 outbox、心跳、重试策略）；不支持的数据库直接报错。
- advisory lock 等 PostgreSQL 专属逻辑改用 `is_postgresql` 判断。

### 3. 保留的运行差异

- 复核后确认：SQLite 下 outbox 与主动 Coach 采用“请求时消费”，是单写者模式下的有意设计，功能可用，只是触发方式不同。为 SQLite 增加后台写入者会加剧写锁竞争，本次不改。此前评审中“两边功能不一样”的说法据此修正。

## 新约定

- 所有 schema 变更只新增 Alembic revision，并能在 SQLite 与 PostgreSQL 上执行（SQLite 修改约束用 `op.batch_alter_table`）。
- `_run_lightweight_migrations` 已冻结；`tests/test_sqlite_alembic_runtime.py` 用源码摘要拒绝对它的修改。
- 业务代码不直接判断 `dialect.name`，改用 `app/utils/dialect.py`。

## 涉及文件

- 后端：`app/database.py`、`alembic/env.py`、`run_migrations.py`、`app/utils/dialect.py`（新增）、`app/utils/operation_lock.py`、`app/utils/sync.py`、`app/routers/notes.py`、`app/services/{knowledge_source,profile,retrieval_projection,knowledge_projection,extraction_budget,projection_outbox}_service.py`、`app/services/review_schedule_identity.py`
- 构建：`scripts/build_desktop_installer.ps1`
- 测试：`tests/test_sqlite_alembic_runtime.py`、`tests/test_dialect_adapter.py`（新增）
- 文档：`backend/README.md`、`docs/technical.md`、`启动指南.md`

## 验证

- SQLite 迁移：全新文件、已有版本文件、无版本旧文件（含数据保留与二次启动）均升级到 head；旧文件补齐后仅有上述两类已知差异。
- 真实启动：用 uvicorn 分别以全新文件和 v1.3 形态旧文件启动，`/health` 均为 200，版本为 `20260928_31`，旧用户数据保留，应用日志未被迁移重置。
- PostgreSQL 16（本机一次性容器，按 CI 步骤）：空库 `run_migrations.py` 成功；迁移后及发布门禁后 `alembic check` 均无差异；`test_postgres_release_gate.py` 10 passed；`test_hardening_postgres.py` 1 passed。方言收拢初版把引擎对象判成“非 PostgreSQL”，导致 advisory lock 被跳过，正是由该 PG 门禁发现并修正，`test_dialect_adapter.py` 已覆盖。
- 后端完整回归（SQLite）：**812 passed、52 skipped、70 subtests passed**，约 302 秒，pytest 退出码 0；本批开始前同一工作区为 804 passed，新增的 8 项全部通过。本批无前端改动。

## 已知限制

- 桌面打包脚本的改动未在 Windows 上实际打包验证。
- 未运行 `ci_postgres_upgrade_rehearsal.sh`（历史 dump/restore 演练，需本机 PostgreSQL 客户端工具）。
- 旧 SQLite 文件缺少 `wrong_questions.concept_id` 外键约束。
