# Mnemox V2 Neo4j / Graphiti Implementation Plan

> **Goal:** 在不破坏 SQL Canonical、SQLite desktop fallback 和现有 Association V2 的前提下，把 Neo4j 建成真实可选 Graph Backend，并完成至少一个 Graph-native 产品能力；同时把 Graphiti 做成独立 Temporal/Episodic Vertical Slice，形成可运行、可比较、可面试复盘的完整技术演进。

**Architecture:** PostgreSQL / SQLite 继续承担事实、事务、审核、Evidence 和 Temporal Truth；通过 Transactional Outbox 生成可重建 Projection。Neo4j 只承担 Graph Execution；Graphiti 只承担可选 Temporal/Episodic Projection。所有新能力必须有 SQL fallback 或明确 feature flag，默认部署不强制启动 Neo4j / Graphiti。

**Tech Stack:** Python 3, FastAPI, SQLAlchemy async, PostgreSQL / SQLite, Neo4j 5.26+, Neo4j Python Driver 6.3+, graphiti-core 0.30.x, Chroma, FTS5 / PostgreSQL FTS, pytest, Docker Compose.

**Authoritative design:** `docs/superpowers/specs/2026-09-04-mnemox-v2-graph-evolution-and-portfolio-architecture.md`

---

## Phase 0：先冻结领域模型，不急着写新功能

### Task 0.1：审查 Node / Edge / Lifecycle

> 2026-09-04：**已完成第一轮冻结审查。** 领域契约见 `docs/superpowers/specs/2026-09-04-mnemox-v2-graph-domain-contract.md`。结论是不新增 Neo4j 专用领域表，保留 SQL Canonical；重点补齐 GraphStore 的完整 path / direction storage-neutral DTO。Stage 6 为 Association parity 使用的双向遍历被明确为 query policy，不再等同 Canonical relation direction。

**目标：** 确保未来迁移的是正确的领域模型，而不是把错误模型投影到更复杂的数据库。

**重点文件：**
- Review: `backend/app/models/knowledge.py`
- Review: `backend/app/models/concept.py`
- Review: `backend/app/models/memory.py`
- Review: `backend/app/services/graph_store/base.py`
- Create/Update: graph schema documentation if needed

- [x] 列出当前所有潜在 Node：`Claim`、`Concept`、`Source`、`MemoryDeclaration`、未来 `Goal` / `Skill` / `LearningState`。
- [x] 列出当前所有 Edge：ClaimRelation、ClaimConceptLink、ConceptEdge、Source ownership / evidence references。
- [x] 明确每种 Edge 的方向、是否对称、是否可逆。
- [x] 明确哪些 Edge 必须有 Evidence，哪些只允许 confirmed 后进入产品图。
- [x] 明确来源版本变化后 Edge 如何失效。
- [x] 明确 Temporal 属性属于 Canonical 还是 Projection。
- [x] 检查是否存在“把 Concept relation 塞进 Claim relation”之类的建模混淆。

**退出标准：**
- 新增一张稳定 Graph Domain 表格 / Mermaid 图；
- 每种 Relation type 都能用一句话说明语义和生命周期；
- 没有为了 Neo4j 而新增只服务数据库实现的领域概念。

**学习 / 面试检查点：**
- 能解释 Property Graph 与 relational schema 的区别；
- 能解释为什么 Canonical model 不应该由 Neo4j schema 反向定义。

---

## Phase 1：把 GraphStore 真正做成可替换执行层

### Task 1.1：扩展 GraphStore 契约

> 2026-09-04：**GraphStore 契约与 Knowledge Path V1 已完成。** 已新增 storage-neutral `GraphNodeRef / GraphEdgeRef / GraphPath`、显式 traversal direction 语义和 `find_concept_paths(...)` 能力边界；`Neo4jGraphStore` 已实现 bounded path traversal，`SqlGraphStore` 继续对通用 path search 明确返回 capability unsupported，避免为了 parity 自研通用图引擎。产品响应会回到 Canonical SQL 重载 Concept、ConceptEdge、LearnerEvidence 与 provenance。旧 `GraphHit.path` 暂时只保留 Association V2 兼容。

**目标：** 上层业务只表达“我要什么图语义”，不关心 SQL / Cypher。

**重点文件：**
- Modify: `backend/app/services/graph_store/base.py`
- Modify: `backend/app/services/graph_store/sql_store.py`
- Modify: `backend/app/services/graph_store/neo4j_store.py`
- Modify: GraphStore contract tests

- [x] 保留现有 `expand_claims / expand_concepts / source_claims`。
- [x] 增加稳定的 path query result 数据结构，能表达完整节点/边路径而非只返回候选 ID。
- [x] 为 Knowledge Path 预留 `find_concept_paths(...)` storage-neutral contract。
- [x] depth / relation types / direction / limit 都由业务参数表达，不泄露 Cypher。
- [x] SQL backend 只保留当前能自然支持的 bounded/fixed path；通用 path search 明确 capability unsupported，不为 parity 自研通用图引擎。

**退出标准：**
- Association / Router / UI 不 import SQLAlchemy graph query details；
- Neo4j 与 SQL 返回同一 storage-neutral DTO；
- 现有 56-case Association 不回归。

### Task 1.2：增加后端选择器

> 2026-09-04：**Optional Runtime、Phase 3.1 Knowledge Path、Phase 3.2 Explainable Multi-hop 与 Phase 5 Graphiti Temporal Slice 均已收口。** `GRAPH_BACKEND=sql|neo4j` 默认 SQL；旧 `NEO4J_GRAPH_ENABLED/SHADOW` 不决定产品查询后端。Neo4j selector、projection readiness/fallback/rollout、bounded path 与 SQL overlay 已通过真实 Neo4j；Graphiti Temporal Slice 也已通过真实 Graphiti 0.30.x + Neo4j current/as-of/delete/rebuild 门禁。当前只剩 Phase 7 最终工程收口，以及 Stage 7 后通过 WebUI 导入真实笔记做中文/双语人评与长期灰度。

**目标：** Neo4j 从 Shadow-only 变成真正可选 backend，但默认仍是 SQL。

建议配置：

```text
GRAPH_BACKEND=sql
GRAPH_BACKEND=neo4j
```

**重点文件：**
- Modify: `backend/app/config.py`
- Modify: `.env.example`
- Modify: `backend/env.example`
- Modify: `backend/app/services/graph_store/factory.py`
- Add tests for selection / fallback / invalid config

- [x] 默认 `sql`。
- [x] `neo4j` 只有配置完整时才创建 Optional Neo4j runtime；缺 credential fail closed。
- [x] 查询时故障有明确 SQL fallback 与 request-scoped diagnostics；配置错误不静默切后端。
- [x] Desktop / SQLite 模式默认 SQL，不要求 Neo4j 服务。
- [x] `NEO4J_GRAPH_SHADOW` 与正式 `GRAPH_BACKEND=neo4j` 语义分离。

**退出标准：**
- 同一业务测试可分别在 SQL / Neo4j backend 运行；
- 切换不修改 Association 业务代码。

**学习 / 面试检查点：**
- Strategy / Adapter / Dependency Inversion；
- 为什么“可插拔 backend”比业务代码直接调用 Cypher 更可维护。

---

## Phase 2：把 Neo4j 从“能查询”做到“可运行”

### Task 2.1：Projection lifecycle 收口

**目标：** Neo4j 即使作为可选正式 backend，也必须始终可重建。

**重点文件：**
- Modify: `backend/app/services/knowledge_projection_service.py`
- Modify: `backend/app/services/knowledge_projection_worker.py`
- Modify: `backend/app/services/graph_store/neo4j_store.py`
- Tests: projection / retry / DLQ / rebuild / delete / isolation

- [x] 全量 `rebuild_user` 保持幂等；真实 Neo4j 上连续 rebuild 已复验。
- [x] 已评估增量投影：当前保留 rebuild-only，并用 dirty propagation + bounded two-slot coalescing 控制重建；只有真实规模证明 rebuild lag/cost 不可接受才升级 per-source / per-claim 增量投影。
- [x] source / Claim / Concept / relation mutation 会标记 graph dirty；source delete 真机验证无旧 Claim 残留。
- [x] projection lag、oldest pending、failed、DLQ 与 initialization 已暴露到 authenticated Knowledge Status；Graph runtime readiness 联合 primary health、初始化与 projection caught-up 判断。
- [x] Neo4j property inspection 验证不保存 Claim statement / Unit text / Evidence excerpt / title/content 等不需要正文。
- [x] wrong credential / 断连路径不破坏 Canonical SQL transaction；读路径安全回落 SQL。

**退出标准：**
- disposable Neo4j 真机 integration 全过；
- 删除 / rebuild / isolation / auth failure / DLQ 全有测试；
- Neo4j 故障不影响 Canonical 写入。

### Task 2.2：Fallback 与灰度

> 2026-09-04 fallback policy 冻结：GraphStore 的**读查询**由 storage-neutral decorator 执行 `Neo4j -> SQL` 降级，避免 Association/Router 散落数据库分支；`rebuild_user / delete_source` 属于 Projection 运维，失败必须显式暴露，不允许用 SQL no-op 冒充成功；graph-native capability 只有 SQL backend 自然支持时才允许降级，否则返回 capability unavailable。每次 fallback 只记录 backend / error type / latency，不记录异常 message、query/body。

- [x] `GRAPH_BACKEND=neo4j` 的现有 GraphStore **读查询**已有明确 SQL fallback policy；Projection 运维和 SQL 不支持的 graph-native capability 不伪降级。
- [x] diagnostics 记录 backend / fallback error type / latency，不记录异常 message、敏感 query/body；Association V2 已返回 request-scoped `graph_runtime` diagnostics。
- [x] 支持环境级稳定百分比灰度 `NEO4J_GRAPH_ROLLOUT_PERCENT` 与用户级 canary allowlist `NEO4J_GRAPH_ROLLOUT_USER_IDS`；只有 rollout selected + initialized + caught-up 才尝试 Neo4j，否则直接 SQL。
- [x] Shadow 模式继续与正式 selector 分离，并保留用于新 Cypher / 新图功能上线前 parity 验证。

**学习 / 面试检查点：**
- CQRS；
- Transactional Outbox；
- eventual consistency；
- projection lag；
- rebuildable read model；
- shadow traffic / dark launch。

---

## Phase 3：实现第一个真正的 Graph-native 产品能力

### Task 3.1：Knowledge / Learning Path

**目标：** 不只是把已有 SQL query 改写成 Cypher，而是实现一个路径类产品能力。

示例：

```text
已掌握：Tool Calling
目标：LangGraph

Tool Calling
  → Agent Runtime
  → State Management
  → Workflow
  → LangGraph
```

**后端能力：**

- [x] 输入：当前用户、起点 Concept、目标 Concept、最大深度、允许 Relation type。
- [x] 图查询：寻找 bounded shortest / best path。
- [x] 叠加用户 mastery / evidence：标出已掌握、薄弱、缺失节点。
- [x] 返回 path explanation：每一步 Edge 类型、ConceptSourceEvidence / manual provenance；不编造无依据解释。
- [x] 无 Neo4j / 不在 rollout / projection stale 时明确返回“高级路径能力不可用”，基础产品继续走 SQL；不为 parity 新造通用 SQL BFS。
- [x] 防环、用户隔离、confirmed/current projection gate 与 SQL rehydrate 校验。

**API：**
- [x] 已新增 `POST /api/knowledge/learning-path`，并先冻结 `docs/superpowers/specs/2026-09-04-mnemox-v2-knowledge-learning-path-contract.md`。

**退出标准：**
- [x] 合成 path cases 覆盖 direct / multi-hop / multiple path / no path / cycle / direction / related_to / weak-unseen / missing evidence / cross-user / stale rollout；
- [x] shortest-first + equal-depth confidence ordering 可核对；
- [x] 0 cross-user；
- [x] 路径每一步可追溯到 confirmed Evidence、manual provenance 或明确 `missing_evidence`；
- [x] 真实 disposable Neo4j 5.26 path integration 通过；Stage 0～7 Knowledge 宽回归加入 Knowledge Path 后为 `122 passed`。

### Task 3.2：Explainable Multi-hop Association

**目标：** Association 不只告诉用户“相关”，还告诉用户“为什么相关”。

> 2026-09-04：**Phase 3.2 V1 已完成。** 新增独立 default-off flag `ASSOCIATION_MULTIHOP_EXPLANATION_ENABLED`；解释层位于排序后的 optional enrichment，不改变 Ranker 分数/顺序。Graph path 只负责发现 topology，Concept / ConceptEdge / provenance 必须回到 Canonical SQL rehydrate；新 `explanation` surface 不暴露 Claim/Concept/Edge SQL ID、Neo4j key 或 Cypher。

- [x] 返回完整图路径摘要；
- [x] presentation-safe steps 可表达 `Claim → Concept → prerequisite/related_to → Concept → Claim`；
- [x] path explanation 不泄露内部数据库 ID；
- [x] Edge provenance 返回 confirmed evidence / confirmed manual / explicit missing evidence；
- [x] 无有效 path、stale/outside rollout、Neo4j failure 时不编造解释，只省略 enrichment；原 Association 结果继续可用。

**退出标准：**
- [x] shared Concept、one/multi-hop、方向、related_to、provenance、跨用户拒绝、故障隔离均有测试；
- [x] explanation flag 开/关不改变 Association ranking/order/score；
- [x] 加入 Phase 3.2 后 Stage 0～7 Knowledge 宽回归（含真实 Neo4j）为 `127 passed`。

**学习 / 面试检查点：**
- shortest path；
- bounded traversal；
- path explainability；
- graph query vs relational JOIN trade-off。

---

## Phase 4：可选 Graph Analytics，只做一个有产品意义的

只在 Phase 3 完成后选择 **一个**，不同时做全部：

### Option A：Bridge Concept

找连接两个知识簇的重要桥接概念，用于“你缺的关键中间概念”。

### Option B：Knowledge Community

把用户知识图分成自然主题簇，用于知识地图导航。

### Option C：Central Concept

识别知识图中的核心概念，但必须避免把纯 Degree 当成“用户最重要知识”。

**退出标准：**
- 有明确 UI / Recommendation 用途；
- 有解释，而不是为了展示算法名。

**学习 / 面试检查点：**
- centrality；
- community detection；
- 图算法结果为什么不能直接当业务真相。

---

## Phase 5：Graphiti Temporal / Episodic Vertical Slice

### Task 5.1：限定 Episode 输入边界

> 2026-09-04：**已完成。** Stage 7 V1 只投影 SQL 中 reviewed `MemoryDeclaration`；不默认摄入聊天原文，不接管 Memory Truth。实现采用 Graphiti 0.30.x 的 Entity/RELATES_TO schema + BM25 search，使用本地固定零向量满足 Graphiti/Neo4j 存储契约，LLM / embedding / cross-encoder 外部调用均为 0。

**目标：** Graphiti 只解决它真正擅长的问题，不接管整个 Memory。

第一版只使用：

- reviewed temporal declarations；
- 明确 opt-in 的 synthetic / anonymous learning episodes；
- 后续可评估 selected conversation episodes。

禁止：

- 默认摄入所有聊天原文；
- 让 Graphiti 成为唯一 Memory Truth；
- 绕过 `confirmed / staged / conflict` 审核语义。

### Task 5.2：Temporal Graph 场景

实现固定场景：

```text
Sep 01  learning_focus = Tool Calling
Sep 10  learning_focus = Agent Runtime
Sep 20  learning_focus = LangGraph
```

支持：

- [x] 当前事实查询；
- [x] as-of 历史查询；
- [x] fact invalidation；
- [x] correction / supersede；
- [x] cross-user isolation；
- [x] group delete / rebuild。

### Task 5.3：SQL Temporal vs Graphiti 对照

必须记录：

- [x] correctness；
- [x] ingestion latency；
- [x] search latency；
- [x] LLM token / embedding usage；
- [x] configured cost；
- [x] invalidation correctness；
- [x] code complexity；
- [x] failure recovery；
- [x] privacy / deletion behavior。

Stage 7 model-free benchmark：60 / 300 temporal declarations 的 SQL 与 Graphiti correctness 均为 `1.0`，Graphiti p95 约 `192.20ms / 138.55ms`，SQL p95 约 `4.77ms / 2.92ms`；Graphiti rebuild 约 `2.31s / 9.30s`。删除后 projection 变为 not caught-up，再 rebuild 可恢复；cross-user leakage、LLM 调用、embedding 外部调用均为 `0`。因此 Graphiti 保持 Experimental，不进入默认 Runtime。

**退出标准：**
- 不要求 Graphiti “胜出”；
- 要求可以清楚解释什么场景它比 SQL Temporal 更自然、什么场景不值得用。

**学习 / 面试检查点：**
- episodic memory；
- temporal knowledge graph；
- bi-temporal / valid-time 思想；
- fact invalidation；
- temporal graph vs relational temporal model。

---

## Phase 6：真实数据验收

> 工程 Stage 7 收口不再阻塞于陌生用户数据。真实匿名中文/双语的人评将在 Stage 7 完成后，通过用户自己的真实技术笔记 + WebUI dogfooding 执行；本阶段先保留下面的验收矩阵作为上线前产品校准项，不伪造“真实用户”结论。

### Task 6.1：真实匿名中文 / 双语知识集

- [ ] 选取真实匿名技术笔记 / 学习资料；
- [ ] 覆盖中文、英文、中英混合；
- [ ] 长文与碎片笔记；
- [ ] 真实 Claim / Concept / Relation；
- [ ] 人工标注 Association / Path 是否合理。

### Task 6.2：Benchmark Matrix

至少记录：

| 维度 | SQL | Neo4j | Graphiti / Temporal SQL |
| --- | --- | --- | --- |
| 1-hop | | | |
| 3-hop | | | |
| shortest path | | | N/A |
| dynamic relation | | | N/A |
| p50 / p95 | | | |
| memory / disk | | | |
| projection lag | N/A | | |
| rebuild | N/A | | |
| correctness | | | |
| user isolation | | | |
| code complexity | | | |

不要只保留“谁快”，还要保留“为什么”。

---

## Phase 7：上线前产品与工程收口

### Task 7.1：默认部署边界

上线第一版建议：

```text
Default:
PostgreSQL / SQLite
Chroma
Sparse
SqlGraphStore

Optional server profile:
Neo4j
Neo4jGraphStore
Knowledge Path / advanced graph features

Experimental:
Graphiti Temporal Slice
```

- [x] 默认 Compose 不强制 Neo4j；`docker compose config --services` 仅包含 `db/backend/frontend`。
- [x] Neo4j profile 可一键启动；`--profile graph` 才额外包含 `neo4j`，并保留 `graph-shadow` 兼容 alias。
- [x] Graphiti 默认关闭；`GRAPHITI_ENABLED=false`，Temporal API 另有 409 feature gate。
- [x] 生产秘密 / 密钥不进入 repo；生产 `DB_PASSWORD/SECRET_KEY` 继续由环境显式提供，Graph 测试默认值仅限本地可丢弃 profile。
- [x] Windows desktop 继续 SQL fallback；`GRAPH_BACKEND=sql` 是默认值，Neo4j 不属于默认 Compose/desktop 必需依赖。

### Task 7.2：最终回归

- [x] Stage 0～7 Knowledge/Temporal 宽回归：`149 passed, 1 warning`；
- [x] Association V1 / V2：V2 包含在宽回归，V1 + migration/GraphStore 补充门禁 `35 passed`；
- [x] SQL / Neo4j backend contract；
- [x] real Neo4j integration：Shadow + Knowledge Path 合计 `4 passed`，显式真机执行、无 skip；
- [x] Graphiti integration：Stage 6 与 Stage 7 Temporal 各 `1 passed`，显式真机执行；
- [x] migration / compose：schema migration 回归通过；默认 Compose 与 `graph` profile 服务集合已验证；
- [x] frontend build / test / lint：`27 files / 93 tests passed`，production build 与 ESLint 通过；
- [x] `git diff --check`：最终收口再次执行并记录，仅保留既有 PowerShell LF/CRLF 提示，不存在 whitespace error。

---

## Phase 8：把项目整理成真正能用于学习 / 面试的工程材料

### Task 8.1：Architecture Story

> 2026-09-04：**已完成。** 见 `docs/superpowers/specs/2026-09-04-mnemox-v2-stage7-architecture-story.md`，包含完整演进图、Stage 6/7 决策衔接、真实 benchmark、部署边界和可展开的面试表述。

README / docs 至少有一张演进图：

```text
Chunk RAG
  ↓
Canonical Claim / Evidence
  ↓
Concept / Relation
  ↓
SqlGraphStore
  ↓
Sparse + Dense + Graph Retrieval
  ↓
Neo4j Shadow
  ↓
Optional Neo4j Backend
  ↓
Knowledge Path / Explainable Multi-hop
  ↓
Graphiti Temporal Experiment
```

### Task 8.2：保留 ADR 和 Benchmark

> 2026-09-04：**已完成 Stage 7 工程证据整理。** Graph Domain、Stage 6 Go/No-Go、Graph Evolution、Knowledge Path、Explainable Multi-hop、Graphiti Temporal Slice 与 Architecture Story 均保留对应 ADR/update/benchmark；真实笔记人评仍明确后置到 WebUI dogfooding。

至少能回答：

1. 为什么最开始不用 Neo4j？
2. 为什么 SQL 是 Canonical？
3. Transactional Outbox 解决什么问题？
4. Shadow 怎么避免直接切流事故？
5. 为什么 5,000 Claim 下 Neo4j 不是全面更快？
6. 为什么后来仍然决定实现 Neo4j？
7. 为什么 Graphiti 不直接替代 `MemoryDeclaration`？
8. Graphiti 和 Neo4j 根本区别是什么？
9. 如果 Neo4j 挂了怎么办？
10. 如果用户删除资料，Chroma / Neo4j / Graphiti 怎么同步清理？

### Task 8.3：准备简历 / 面试表述

> 2026-09-04：Architecture Story 已提供一段可直接练习但不要求死记的面试版表述，以及 10 个可继续追问的实现问题。

最终应该能形成类似表述：

> 将 PostgreSQL 作为 Claim / Evidence / Temporal Fact 的 Canonical Store，通过 Transactional Outbox 构建 Chroma、Sparse FTS 与 Neo4j 可重建投影；抽象 GraphStore 支持 SQL / Neo4j 双后端，并通过 Shadow Traffic 对 ID、Path、Score 做一致性验证。基于真实 benchmark，没有盲目全量切换，而是在 Knowledge Path、Explainable Multi-hop 等 graph-native 场景使用 Neo4j，并保留 SQL fallback。另用 Graphiti 对 Episodic Temporal Memory 做独立对照，避免和已有 Temporal SQL 形成双事实源。

这里的目标不是背这段话，而是做到每一句都能展开讲实现细节和 trade-off。

---

# 推荐执行顺序

如果时间窗口约 2～4 周，优先级：

```text
P0 领域模型 / GraphStore 契约
  ↓
P1 Optional Neo4j Backend
  ↓
P2 Knowledge Path
  ↓
P3 Explainable Multi-hop Association
  ↓
P4 真实数据 / Benchmark
  ↓
P5 Graphiti Temporal Slice
  ↓
P6 可选一个 Graph Analytics
  ↓
P7 上线收口 + Architecture Story
```

如果时间不够，**宁可不做 Graph Analytics，也必须把 Neo4j Backend + Knowledge Path + Graphiti Temporal Slice + Benchmark 做完整。**

---

# Stop Conditions

遇到以下情况暂停继续加功能：

- Neo4j 需要成为 Canonical 才能实现需求；
- Graphiti 需要绕过审核 / Evidence / privacy；
- 新功能没有真实产品入口，只是为了增加技术名词；
- 真实数据表明路径结果缺乏产品价值；
- 为保持 SQL / Neo4j parity 导致业务层被数据库实现细节污染；
- 全量回归持续失败而继续堆新模块。

原则：

> **先做深，再做多；每一项技术都必须有问题、实现、数据、取舍和回滚。**
