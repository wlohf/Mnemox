# 2026-09-04 Mnemox V2 Stage 7：Graph Domain / GraphStore 地基

> **后续状态说明（同日）：** 本文记录 Stage 7 第一检查点，因此下方 `38 passed, 2 skipped` 和“灰度/真机待做”属于当时快照。Phase 2 随后已完成 rollout、projection initialization/caught-up stale gate、rebuild lifecycle 与真实 Neo4j parity；当前状态和 `104 passed, 0 skipped` 证据见 `2026-09-04_mnemox-v2-stage7-neo4j-rollout-readiness.md`。本文保留用于解释演进顺序，不覆盖历史检查点。

## 本轮范围

本轮只完成 Stage 7 的第一层承重结构，不实现 Knowledge Path、Graphiti Temporal Slice 或生产灰度。

1. 完成 Phase 0 Graph Domain 冻结。
2. 开始 Phase 1 GraphStore storage-neutral contract。
3. 建立显式 `GRAPH_BACKEND=sql|neo4j` selector。
4. 让 Neo4j runtime selection 与 Projection Outbox / worker target 保持一致。
5. 保留 Stage 6 Shadow / Benchmark / NO-GO 历史证据。

## 为什么先做这个

Stage 6 的 SQL / Neo4j 查询主要为 Association parity 服务。为了扩大召回，它们会把部分有向关系按双向邻接遍历；这不等于 Canonical relation 本身无方向。

Knowledge/Learning Path 对方向非常敏感，例如：

```text
Tool Calling -> prerequisite_of -> Agent Runtime
```

因此 Stage 7 先把两件事拆开：

```text
Canonical relation direction
!=
Query traversal direction
```

随后 GraphStore 再用 storage-neutral DTO 表达完整 path，而不是把 SQLAlchemy / Cypher 或松散 dict 泄露给 Association / Router / UI。

## 领域结论

详见：

`docs/superpowers/specs/2026-09-04-mnemox-v2-graph-domain-contract.md`

关键结论：

- Claim / Concept 是正式知识节点。
- Source / Unit 是 provenance / lifecycle projection 辅助节点，不成为第二套知识真相。
- `prerequisite_of` 固定为 prerequisite -> dependent。
- `analogous_to`、`related_to` 具有对称语义，但 Canonical 不重复制造两条反向边。
- Claim 必须满足 confirmed + active + current revision + active source + Evidence 才进入产品图。
- Temporal `valid_from / valid_to / supersedes / conflicts` 继续属于 SQL Canonical。
- MemoryDeclaration 不进入当前 Neo4j Knowledge Graph 主链；Graphiti 后续独立验证。
- 不新增 Neo4j 专用 Canonical 表。

## GraphStore 变化

新增：

```text
GraphNodeRef
GraphEdgeRef
GraphPath
TraversalDirection = outgoing | incoming | both
GraphCapabilityUnsupported
```

`GraphEdgeRef` 同时保存：

- Canonical `from_node -> to_node`；
- 本次 traversal 是否 `traversed_forward`。

这样 Association 可以明确选择双向邻接，而 Learning Path 可以坚持沿先修方向前进。

旧 `GraphHit.path: tuple[dict, ...]` 暂时保留，目的是不破坏 Association V2。新 graph-native 功能不得继续扩展该弱类型结构。

`SqlGraphStore.find_concept_paths()` 当前明确返回 capability unsupported。原因不是 SQL 做不到，而是本阶段禁止为了保持双 backend parity，在 SQL 中重新实现通用 shortest path / BFS path reconstruction。

## Optional Backend selector

新增：

```text
GRAPH_BACKEND=sql      # default
GRAPH_BACKEND=neo4j    # optional server backend
```

规则：

- 旧 `NEO4J_GRAPH_ENABLED` / `NEO4J_GRAPH_SHADOW` 不再决定产品查询 backend。
- `GRAPH_BACKEND=neo4j` 缺少 Neo4j credential 时 fail closed，不静默切换。
- runtime Neo4j driver 使用进程级共享 executor，并在 FastAPI shutdown 时关闭。
- `GRAPH_BACKEND=neo4j` 同时启用 `neo4j_graph` Projection Outbox / worker target。
- Stage 6 Shadow 仍可独立运行，不影响正式 selector。

这个联动很重要：如果只切查询 backend 而不启用 projection worker，系统会读取 stale / empty Neo4j projection。

## 本检查点当时尚未完成

本轮**不宣称 Optional Neo4j Backend 已生产完成**。仍缺：

1. 灰度策略；
2. `find_concept_paths()` 的 Neo4j shortest/best path 实现；
3. Knowledge Path mastery/evidence overlay；
4. real Neo4j integration 在本机真实服务上的复验。

本轮已补齐 authenticated runtime readiness：`/api/knowledge/status` 的 `graph_runtime` 会同时返回 selected backend、primary health、projection caught-up、blocking counts 与 fallback serving readiness。Neo4j 只有在连接健康且当前用户没有 pending / processing / failed / DLQ projection 任务时才算 `primary_ready=true`；SQL fallback 可用时仍可 `serving_ready=true`。

已有 read fallback：factory 在 `GRAPH_BACKEND=neo4j` 时返回 request-scoped `FallbackGraphStore`，现有读查询失败后使用 `SqlGraphStore`；Projection `rebuild/delete` 不伪 fallback，SQL 不支持的 graph-native capability 也不会被冒充为成功。fallback diagnostics 只保存异常类型与延迟，不保存异常 message/query/body。

## 测试证据

执行：

```bash
cd backend
venv/bin/python -m pytest -q \
  tests/test_graph_runtime_status.py \
  tests/test_graph_store_contract.py \
  tests/test_association_v2.py \
  tests/test_graph_shadow_stage6.py \
  tests/test_neo4j_shadow_integration.py
```

结果：

```text
38 passed, 2 skipped, 1 warning
```

其中两个 skip 为当前环境没有配置真实 Neo4j integration 服务；不是功能失败。

已覆盖的本地契约包括：

- Graph path Canonical direction / reverse traversal 表达；
- SQL generic path capability 明确拒绝；
- backend selector 默认 SQL；
- legacy Neo4j flag 不暗中切 product backend；
- Neo4j 缺凭据 fail closed；
- `GRAPH_BACKEND=neo4j` 会启用 Neo4j projection target；
- Neo4j read failure 会走 SQL fallback，且 diagnostics 不泄露异常 message/query/body；
- Projection rebuild failure 不会被 SQL fallback 伪装成成功；
- health 语义区分 `primary ok` 与 `serving via fallback`；
- runtime readiness 将 Neo4j connectivity 与 projection caught-up 联合判断，不把“能连上但图已落后”误判成 ready；
- readiness 失败时只暴露异常类型，不暴露异常正文；
- Stage 6 Shadow parity / user isolation / rebuild / delete / retry-DLQ 相关既有回归继续通过；
- Association V2 无回归。

Graphiti 依赖产生 1 条 Pydantic v2 deprecated warning，属于第三方 `graphiti_core` 的 class-based config 警告，本轮没有修改其行为。

## 下一步（本检查点当时）

当时计划继续 Phase 1/2 边界收口：

```text
Neo4j backend readiness / projection lag  ✅
-> gray rollout policy
-> backend parity / real Neo4j integration
-> 再进入 Knowledge Path
```

在这些能力完成之前，不把当前 dirty checkout 或 Optional Neo4j Backend 宣称为 merge-ready / production-ready。
