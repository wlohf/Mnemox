# Mnemox V2 Graph Domain Contract

> 日期：2026-09-04  
> 状态：**Stage 7 Phase 0 冻结基线**  
> 上位决策：`2026-09-04-mnemox-v2-graph-evolution-and-portfolio-architecture.md`  
> 原则：SQL 是 Canonical；GraphStore 表达业务图语义；Neo4j/其他图执行层不得反向定义 Canonical model。

## 1. 这份文档解决什么

Stage 6 的 `SqlGraphStore` / `Neo4jGraphStore` 已能完成固定 Association 查询，但它们最初是为 Shadow parity 服务的：重点是“同一批 Claim 是否命中”，不是“完整、方向明确、可解释的路径语义”。Stage 7 要继续做 Knowledge/Learning Path，因此必须先冻结领域模型，避免把 Association 为召回方便采用的双向遍历误当成 Canonical relation 方向。

核心约束：

```text
Canonical relation direction
!=
Query traversal direction
```

例如 `A prerequisite_of B` 的 Canonical 方向永远是 `A -> B`。Association 可以显式要求 `both` 方向找邻居，但 Learning Path 默认只能沿先修方向前进。

## 2. Node 边界

| Node | Canonical | Stage 7 Projection | 产品图职责 | 当前结论 |
| --- | --- | --- | --- | --- |
| Claim | SQL `claims` | Neo4j `:Claim` | 原子知识陈述 | **正式 Node**。只有 confirmed + active + current revision + active source + 至少一条 Evidence 才进入产品图 |
| Concept | SQL `concepts` | Neo4j `:Concept` | 稳定知识概念、路径骨架 | **正式 Node**。只投影当前用户 confirmed Concept |
| Source | SQL `knowledge_sources` + current Revision | Neo4j `:Source` | provenance / delete / rebuild 边界 | **投影 Node**，不是知识推理真相；版本与正文仍在 SQL |
| Unit | SQL `knowledge_units` | Neo4j `:Unit` | Claim Evidence 的定位桥 | **投影辅助 Node**；不把正文复制进图 |
| MemoryDeclaration | SQL `memory_declarations` | Graphiti slice（未来） | Temporal fact truth | **不进入当前 Neo4j Knowledge Graph 主链**；Graphiti 独立验证 |
| Goal / Skill / LearningState | SQL 各自领域表 | 未来 overlay | Learning Path 个性化覆盖 | **暂不新增图领域实体**；先通过 storage-neutral overlay 使用，避免为 Neo4j 造领域概念 |

## 3. Edge 语义、方向与 Evidence

### 3.1 Claim -> Claim

| Relation | Canonical direction | 对称 | 进入产品图条件 | Evidence / Review 规则 |
| --- | --- | --- | --- | --- |
| `supports` | from Claim -> to Claim | 否 | relation confirmed；两端 Claim 均可见 | 两端 Claim 必须各自有 ClaimEvidence。自动/推断 relation 默认 pending；确认的非人工 relation 应保留 `evidence_provenance` |
| `contradicts` | from -> to | 语义近似对称，但**存储保持有向** | 同上 | 同上。查询层可显式 `both`，不得在 Canonical 中复制反向边 |
| `refines` | coarse -> refined | 否 | 同上 | 同上 |
| `exemplifies` | example Claim -> abstract Claim | 否 | 同上 | 同上 |
| `analogous_to` | canonicalized pair | 是 | confirmed；两端可见 | service 通过 ID 排序只保存一条；查询可双向遍历 |

说明：Stage 6 Association 为召回 parity 把多种 ClaimRelation 用无向方式遍历，这是**查询策略**，不是领域方向定义。Stage 7 DTO 必须记录“边原始方向”和“本次遍历是否逆向”。

### 3.2 Claim -> Concept

| Relation | Canonical direction | 对称 | 规则 |
| --- | --- | --- | --- |
| `about` | Claim -> Concept | 否 | Claim 必须可见；link 必须 confirmed |
| `uses` | Claim -> Concept | 否 | 同上 |
| `applies_to` | Claim -> Concept | 否 | 同上 |
| `exemplifies` | Claim -> Concept | 否 | 同上 |

Claim 本身已有严格 Evidence gate，因此 link 不复制 source excerpt。link 的 provenance 使用 resolution candidate / derivation / mention 等最小元数据；纯 semantic 候选不能自动进入 confirmed graph。

### 3.3 Concept -> Concept

| Relation | Canonical direction | 对称 | 规则 |
| --- | --- | --- | --- |
| `prerequisite_of` | prerequisite -> dependent | 否 | 两端 confirmed；edge confirmed。自动来源必须通过既有 ConceptSourceEvidence / review 生命周期，人工 edge 可由用户确认作为 provenance |
| `related_to` | canonical pair / 双向语义 | 是 | 两端 confirmed；edge confirmed |

**Learning Path 默认只沿 `prerequisite_of` 正向。** `related_to` 可用于补充解释或候选扩展，但不能冒充严格先修关系。

### 3.4 Source / Evidence edges

Neo4j 中的 `Source -> Unit -> Claim` 是 projection provenance 结构，不是新的 Canonical knowledge relation。

- Source version truth：SQL `KnowledgeSourceRevision`。
- Evidence text / locator truth：SQL `ClaimEvidence` / `KnowledgeUnit`。
- Neo4j 只保留重建、删除和 path explanation 所需的最小 ID，不保存 Claim statement、Evidence excerpt、Unit text。

## 4. 生命周期与失效

### Claim

进入图：`confirmed + active + current revision + active source + Evidence exists`。

退出图：任一条件失效即必须在 projection 中消失。来源产生新 Revision 时，旧 Revision Claim 变为 superseded，Projection 必须删除旧 Claim 及其 incident edges。

### Concept / ConceptEdge

- Concept 只在 confirmed 时参与产品图。
- 来源驱动的自动 Edge 在来源版本失效后，按 Canonical SQL 的 evidence cleanup 结果决定保留/删除；Neo4j 不自行判断证据是否仍有效。
- 人工关系不因某一来源删除自动消失，除非 Canonical SQL 规则已经将其删除/拒绝。

### Memory temporal properties

`valid_from / valid_to / supersedes / conflicts` 属于 **Canonical Temporal SQL**。Graphiti slice 可以投影 `valid_at / invalid_at`，但不得成为唯一事实来源。

## 5. 用户隔离

1. 每个 Canonical Node/Edge 都必须能追溯到 `user_id`。
2. GraphStore 所有 query 都必须显式接收 `user_id`。
3. Neo4j Node **和 Relationship** 都继续存 `user_id` 并在 query 中过滤。
4. 禁止通过全局 Concept 名称跨用户复用节点；同名 Concept 在不同用户图中仍是不同 Node。
5. Path result 不因一个合法端点而放松中间节点/边的 user scope。

## 6. 删除语义

| 操作 | Canonical SQL | Projection 要求 |
| --- | --- | --- |
| source delete | tombstone Source / Revision / Claim 并清正文 | 删除 Source、Unit、Claim 及 incident graph edges；不得残留可 traversable path |
| source new revision | 旧 Revision superseded | 删除旧 Claim path，只投影 current revision |
| concept delete/merge | SQL 服务负责身份治理 | graph projection 只执行结果重建/删除，不自行 merge canonical identity |
| user delete | SQL cascade / domain cleanup | 删除该 user_id 的所有 projection nodes / relationships / Graphiti group |
| projection corruption | Canonical 不变 | `rebuild_user` 必须可恢复，不反向写 SQL |

## 7. GraphStore storage-neutral contract

上层只允许表达：

- 起点 Node ID；
- relation types；
- `direction = outgoing | incoming | both`；
- bounded depth / limit；
- 可选目标 Node；
- 要求完整 path explanation。

禁止泄露：

- SQLAlchemy model / clause；
- Cypher string / label / relationship type；
- Neo4j Node/Relationship/Path 对象；
-数据库内部 driver result。

Stage 7 引入三个稳定 DTO：

```text
GraphNodeRef
GraphEdgeRef
GraphPath
```

`GraphEdgeRef` 必须同时表达：

```text
canonical from -> to
traversed_forward = true/false
```

这样 Association 可以选择 `both`，Learning Path 可以选择 `outgoing`，而两者仍共享同一 GraphStore。

旧 `GraphHit.path: tuple[dict, ...]` 暂时保留用于 Association V2 API 向后兼容；新 graph-native 功能不得继续扩展这个弱类型字段。

## 8. SQL 与图引擎职责边界

`SqlGraphStore` 可以继续实现：

- fixed relation pattern；
- 1~3 hop bounded neighborhood；
- 已有 Association fallback。

一旦需求需要通用 shortest path、weighted path、k-shortest、动态 relation combination、community/centrality/PageRank，不继续在 SQL 中维护通用 `frontier / visited / path reconstruction` 引擎。

`Neo4jGraphStore` 承担这些 graph-native execution 能力；SQL 只保留必要的 bounded fallback 或明确 capability unavailable。

## 9. Phase 0 结论

1. **不新增数据库表、不为了 Neo4j 改 Canonical schema。** 当前 Claim / Concept / Evidence / Revision 模型足以进入 Stage 7。
2. 当前最大的契约缺口是 GraphStore path/direction 表达不足，不是数据表缺少节点。
3. Stage 6 的双向遍历实现保留用于 Association parity，但不再代表 Relation domain direction。
4. Stage 7 下一步先扩展 storage-neutral GraphStore DTO/contract，再做 `GRAPH_BACKEND=sql|neo4j` selector。
5. Stage 6 NO-GO Benchmark 和 Shadow 证据全部保留；本决策不修改历史结论。
