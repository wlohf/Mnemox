# 2026-09-04 Mnemox V2 Stage 7：Neo4j Rollout / Readiness / Projection Lifecycle

## 本轮目标

把 Stage 7 的 Optional Neo4j Backend 从“配置上可以选”推进到“可以受控灰度、不会读取 stale graph、Projection 生命周期可闭环、真实 Neo4j 与 SQL 可做 parity 验收”的状态。

本轮仍然**不实现 Knowledge/Learning Path**，也不把 Neo4j 改成默认 Runtime。PostgreSQL / SQLite 继续是 Canonical；Neo4j 仍是可删除、可重建的 Graph Execution Projection。

---

## 为什么不能只做普通 fallback

普通 `Neo4j -> SQL` exception fallback 只能解决：

```text
Neo4j 连接失败 / 查询报错
```

它解决不了更危险的一类问题：

```text
Neo4j 能正常连接
但 Projection 已经落后 SQL
=> 查询成功返回旧图
```

因此 Stage 7 把“Neo4j 能否使用”拆成三个独立问题：

1. 这个用户是否进入灰度 cohort；
2. 这个用户的 Neo4j Projection 是否已经初始化并追平；
3. Neo4j 当前查询是否正常。

只有前两项通过，运行时才尝试 Neo4j；第三项失败时再由已有 `FallbackGraphStore` 回退 SQL。

最终读路径：

```text
GRAPH_BACKEND=sql
  -> SqlGraphStore

GRAPH_BACKEND=neo4j
  -> Neo4jRolloutGraphStore
       |
       |-- user not in rollout ------------> SqlGraphStore
       |
       |-- projection not initialized ------> SqlGraphStore
       |
       |-- projection pending/processing
       |   /failed/DLQ ---------------------> SqlGraphStore
       |
       `-- rollout selected + projection ready
             -> FallbackGraphStore
                  -> Neo4jGraphStore
                  -> on query failure -> SqlGraphStore
```

---

## 灰度策略

新增：

```text
NEO4J_GRAPH_ROLLOUT_PERCENT=100
NEO4J_GRAPH_ROLLOUT_USER_IDS=
```

规则：

- `GRAPH_BACKEND=sql` 时这些配置不生效；默认产品路径仍为 SQL。
- `GRAPH_BACKEND=neo4j` 时，`ROLLOUT_PERCENT` 使用稳定 SHA-256 bucket 对用户做 0～99 分桶，同一用户不会因进程重启随机换桶。
- `ROLLOUT_USER_IDS` 是显式 canary allowlist；命中的用户不受 percentage 限制。
- 环境级灰度通过环境变量控制百分比；用户级 canary 通过 allowlist 控制。
- rollout 只决定“是否允许尝试 Neo4j”，不绕过 Projection readiness。

典型上线顺序：

```text
GRAPH_BACKEND=neo4j
NEO4J_GRAPH_ROLLOUT_PERCENT=0
NEO4J_GRAPH_ROLLOUT_USER_IDS=<internal test users>

-> canary 验证
-> 5%
-> 20%
-> 50%
-> 100%
```

任何阶段都可以把 percentage 降回 `0`，基础图读查询直接回到 SQL。

---

## Projection readiness：连接正常不等于数据可读

新增中立服务：

```text
backend/app/services/graph_projection_status_service.py
```

它不依赖 GraphStore 实现，供：

- Runtime rollout gate；
- authenticated `/api/knowledge/status`；
- Stage 6 Shadow diagnostics；

共同复用，避免 `graph_shadow_service <-> graph_store` import cycle。

### Readiness 判定

对已有 Canonical Graph 数据的用户：

```text
successful Neo4j rebuild required
AND pending == 0
AND processing == 0
AND failed == 0
AND DLQ == 0
```

对完全没有 Canonical Graph 数据的空用户，可以直接认为 Projection initialized，因为 SQL 与 Neo4j 的正确结果都应为空。

这修复了一个重要边界：

```text
旧逻辑：tasks_total = 0 -> backlog = 0 -> caught_up = true

问题：
老用户可能已经有 SQL Claim / Concept / Source，
但从未执行过 Neo4j rebuild。
Neo4j 此时可能是空图，却被误判为 ready。
```

现在这类用户会得到：

```text
initialized = false
blocking_counts.uninitialized = 1
```

并直接使用 SQL。

---

## Projection lifecycle：为什么普通变更也必须重新触发 rebuild

Stage 6 的 Neo4j Projection 主要用于 Shadow，因此此前 `rebuild_user` 更偏显式操作。

进入 Optional Runtime 后，如果 Claim / Concept / Relation 已变化，但 Neo4j Outbox 没重新排队，就会出现：

```text
SQL 已更新
Neo4j 仍是旧图
旧 rebuild row 又是 processed
=> runtime 错误认为图已追平
```

本轮因此补齐 dirty propagation：

- Knowledge object upsert/delete 会重新触发 Neo4j user rebuild；
- ClaimRelation mutation 会标记 Neo4j graph dirty；
- ConceptEdge create/review 会标记 Neo4j graph dirty；
- ClaimConceptLink / concept merge/split/source lifecycle 等经过现有 object projection boundary 的变化也会触发 graph dirty；
- Chroma 全量 rebuild 内部枚举对象时使用 `mark_graph_dirty=False`，避免“为了重建 Chroma 又不断重排 Neo4j”的递归噪声。

当前仍采用**rebuild-only** Neo4j Projection，而不是立即实现 per-claim / per-edge 增量写图。原因是当前数据规模和 benchmark 还没有证明增量复杂度值得承担。

---

## In-flight mutation：两槽 coalescing

单一固定 rebuild row 有一个并发漏洞：

```text
rebuild row = processing
此时 Canonical 又发生变化
若简单忽略 processing row
=> dirty signal 丢失
```

本轮没有改成“每次变更创建一个全量 rebuild 任务”，因为那会在 extraction / merge 等批量变更里造成 rebuild storm。

采用固定两槽：

```text
neo4j:user:<id>:rebuild:v1
neo4j:user:<id>:rebuild:followup:v1
```

语义：

- 主槽 idle/processed -> 变更直接把主槽重排为 pending；
- 主槽 processing -> 变更只排一个 follow-up；
- processing 期间更多变更继续复用同一个 follow-up；
- follow-up processing 时的新变化重新使用已空闲的主槽；
- 单用户最多两个 durable Neo4j rebuild rows，不会无限增长。

`claim_next_knowledge_projection()` 同时禁止同一用户在已有 Neo4j `processing` 任务时 claim 另一个 Neo4j rebuild。

真正执行 `rebuild_user` 时，再复用项目已有：

```text
serialized_user_operation(namespace="neo4j-graph-rebuild")
```

SQLite / 单进程使用 asyncio user lock；PostgreSQL 使用独立连接持有 session advisory lock，因此多实例 worker 下也不会并发执行同一用户的 Neo4j rebuild。

---

## Readiness 与 serving 分离

`/api/knowledge/status -> graph_runtime` 继续区分：

```text
primary_ready
serving_ready
neo4j_read_enabled
effective_backend
rollout
projection
```

示例：

### Neo4j healthy + projection ready + 在灰度

```text
primary_ready = true
neo4j_read_enabled = true
effective_backend = neo4j
serving_ready = true
```

### Neo4j healthy + projection ready + 不在灰度

```text
primary_ready = true
neo4j_read_enabled = false
effective_backend = sql
serving_ready = true
```

这表示“Neo4j 本身没问题，只是这个用户还没被放量”，不能误报成 primary 故障。

### Neo4j healthy + projection stale

```text
primary_ready = false
neo4j_read_enabled = false
effective_backend = sql
serving_ready = true
```

### Neo4j unavailable + SQL fallback healthy

```text
primary_ready = false
serving_ready = true
effective_backend = sql
```

---

## Backend parity 与真实 Neo4j 验收

本轮在本地 disposable：

```text
neo4j:5.26-community
bolt://127.0.0.1:17687
```

上真实执行集成测试，结束后容器与测试 volume 已删除。

真实验收包含：

- wrong credentials -> Neo4j unhealthy，但 Canonical SQL transaction 仍可用；
- `rebuild_user` 连续执行两次结果一致；
- SQL / Neo4j `expand_claims` ID / path type / depth / confidence parity；
- SQL / Neo4j `source_claims` parity；
- 0 cross-user hit；
- Source delete 后旧 Claim 不残留；
- Neo4j node properties 不保存 Claim statement / Unit text / Evidence excerpt / title/content；
- 成功 rebuild marker 后，真实 runtime rollout 走 Neo4j；
- 随后制造新的 Canonical Concept mutation，在 rebuild 未完成时，同一 runtime store 自动改走 SQL，验证 stale gate 真正生效。

### 最终专项回归

执行 Stage 0～7 Knowledge 主链：

```text
knowledge stage0
knowledge source lifecycle
knowledge extraction
entity resolution
knowledge projection
sparse knowledge
association v2
graph store contract
graph rollout / readiness
neo4j projection lifecycle
graph shadow
real neo4j integration
```

结果：

```text
104 passed, 0 skipped, 1 warning
```

其中真实 Neo4j integration **实际运行，不是 skip**。

唯一 warning 仍来自第三方 `graphiti_core` 的 Pydantic v2 class-based config deprecation，本轮未改变 Graphiti 行为。

---

## 本轮没有做什么

仍未完成：

1. `find_concept_paths()` 的 Neo4j bounded shortest / best path；
2. Knowledge/Learning Path API contract；
3. mastery / evidence overlay；
4. Explainable Multi-hop；
5. 真实用户图规模下 rebuild duration / rollout error rate / fallback rate 长期观测；
6. Graphiti Temporal Slice 的 Stage 7 实现。

因此当前结论是：

> **Optional Neo4j Backend 的运行时基础已经具备 selector、projection lifecycle、readiness、stale gate、fallback、灰度和真实 parity 验收；但它还没有第一个 graph-native 产品能力，所以 Stage 7 还没有完成。**

下一施工点进入 Phase 3：先设计并实现 Knowledge / Learning Path。
