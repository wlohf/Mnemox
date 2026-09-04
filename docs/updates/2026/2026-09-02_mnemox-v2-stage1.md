# Mnemox V2 Stage 1：Canonical Claim Schema

## 本周期目标

- 在不启动自动抽取、不改变 Association V1、不替换 Chroma 的前提下，建立 Claim 中心知识图谱的规范 SQL 数据底座。
- 让 Material/Note 具备稳定来源身份、不可变内容版本、可定位 Unit、手工 Claim/Evidence、失效、删除和用户隔离语义。
- 将 Neo4j 与 Graphiti 登记为默认关闭、后续可重建的独立 Shadow 候选；本阶段不安装依赖、不启动服务、不写外部图。

## 已完成

### 1. Canonical SQL 模型

- 新增 `KnowledgeSource`、`KnowledgeSourceRevision`、`KnowledgeUnit`、`Claim`、`ClaimEvidence` 五个模型。
- Source 以 `user_id + source_type + source_record_id` 和稳定 `source_key` 去重。
- Revision 使用内容哈希和部分唯一索引保证每个 Source 最多一个 current 版本。
- Unit 保存有界正文快照、SHA-256 和包含来源键、版本、chunk、字符范围的 locator。
- Claim 在来源版本内按规范化 statement 指纹去重；数据库默认审核状态为 `pending`，手工服务只有在 Evidence 定位成功后才显式写入 `manual + confirmed`。
- Evidence 保存精确摘录和字符范围；没有 Evidence 的 Claim 不能确认为可展示。

### 2. 来源生命周期

- 新增 flush-only `knowledge_source_service`，commit/rollback 继续由路由、领域服务或 worker 拥有。
- `KNOWLEDGE_V2_ENABLED=true` 时，Material/Note 的创建与更新在原事务中登记来源；Obsidian 导入、pull sync、冲突处理、missing 删除、Agent 确认建笔记、演示数据和错题默认资料入口也覆盖。
- 内容不变时复用 current revision；内容或标题变化时生成新 revision，并使旧 revision 与其 active Claim 进入 superseded。
- 删除领域对象前先把来源、所有版本和 Claim 标记 deleted，并清空 Unit 正文、Claim statement 与 Evidence excerpt；重复删除保持幂等。
- 所有读取和写入同时验证 `user_id`、来源状态、current revision、Unit 归属和 Evidence 存在，拒绝跨用户 ID 拼接。

### 3. 双数据库迁移

- Alembic head 升至 `20260902_19`，新增五表、外键、检查约束、唯一约束和查询索引。
- SQLite lightweight migration 支持已有本地数据库幂等补表，并校验关键列和 current revision 部分唯一索引。
- 生产迁移入口把五表纳入 head-only schema 检查；PostgreSQL 仍只能通过 `run_migrations.py` 升级。

### 4. Graph 候选边界

- `NEO4J_GRAPH_ENABLED`、`NEO4J_GRAPH_SHADOW`、`GRAPHITI_ENABLED`、`GRAPHITI_SHADOW` 均默认 `false`。
- SQL 和原始 Material/Note 仍是来源、审核、版本与删除的权威；未来图后端只消费可按用户删除和重建的投影。
- Stage 2～4 形成真实、带 Evidence 的 Claim 和关系数据之前，不启动图 runtime；空图或低质量关系图不会改善当前联想。

## 验证结果

- Stage 0、Stage 1 生命周期与 schema 专项：`34 passed`。
- Stage 1 生命周期单测：`11 passed`，覆盖幂等登记、更新失效、删除脱敏、数据库级 cascade、跨用户拒绝、审核 Evidence、重复 revision 号、current 部分唯一约束、关闭开关零写入及 Material/Note 真实写入入口。
- 关键兼容路径回归：`108 passed`，覆盖 Association V1、概念图、时态记忆、资料检索、Vault、笔记 AI、Agent 写入和事务所有权。
- 完整后端回归：`521 passed, 13 skipped, 58 subtests passed`。
- SQLite 空库/旧库升级与 PostgreSQL offline DDL 通过。
- 全新一次性 PostgreSQL 16 从冻结基线升级到 `20260902_19`；`alembic check` 无 drift；8 项候选门禁全部通过，包括 Claim 生命周期/用户隔离、多 worker、advisory lock 和 AgentRuntime 去重。

## 失败、降级与回滚

- 默认 `KNOWLEDGE_V2_ENABLED=false`，升级 schema 不自动回填历史 Material/Note，也不改变任何现有查询。
- 来源登记与领域写入同事务；登记失败会使整个调用方事务回滚，不留下半完成规范来源。
- 回滚优先关闭总开关并保留新表，不执行破坏性 downgrade；正式生产回滚依赖升级前快照与应用版本同步回退。
- Neo4j/Graphiti 当前没有依赖、容器、凭据、volume 或数据，因此无需外部图清理。

## 尚未实现

- Stage 2 的统一 Pydantic Extraction Schema、确定性/LLM extractor、durable extraction run、自动 pending Claim 和 Grounding worker。
- ClaimConceptLink、ClaimRelation、Entity Resolution、知识专用 Chroma collection、Association V2 与 `SqlGraphStore`。
- Neo4j/Graphiti 的 optional dependency、outbox consumer、按用户 rebuild/delete、Shadow diff、容量/质量/成本 go-no-go。
- Claim 的产品 API 与审核 UI；当前只提供服务层手工创建、审核与可见查询能力。

下一开发阶段是 Stage 2，不是直接切换图数据库。发布候选、历史 PostgreSQL dump 恢复、真实浏览器/Vault/Windows Electron 验收仍按发布轨道独立收口。
