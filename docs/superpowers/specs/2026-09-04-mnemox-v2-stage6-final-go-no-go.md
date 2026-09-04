# Mnemox V2 Stage 6 最终 Go / No-Go 决策

> 日期：2026-09-04  
> 范围：Neo4j GraphStore Shadow、Graphiti Temporal Shadow  
> Stage 6 当时结论：**Neo4j = 默认 Runtime NO-GO；Graphiti = 默认 Runtime NO-GO；Stage 6 完成。**  
> 2026-09-04 后续增量决策：Stage 6 的性能/运维证据保持有效，但因项目同时承担产品、技术学习与工程作品集目标，Stage 7 已按 [图架构演进、技术选型与作品集目标决策](2026-09-04-mnemox-v2-graph-evolution-and-portfolio-architecture.md) 重新打开为 **Optional Neo4j Backend + Graphiti Temporal/Episodic Slice**；默认产品 Runtime 仍不强制启用二者。

## 1. 决策摘要

Stage 6 的目标不是证明“图数据库能运行”，而是回答两个独立问题：

1. 专用 Neo4j 图投影是否相对当前 `SqlGraphStore` 有足够稳定、足够大的净收益，值得增加一个常驻数据库和运维面？
2. Graphiti 的时态图检索是否相对当前 `UserMemory + MemoryDeclaration` Temporal SQL 有明确质量/能力缺口收益，值得增加 Neo4j、向量字段和额外模型调用？

最终答案均为 **否**。

这不是功能失败：两条候选都已经证明可以安全实现。NO-GO 的原因是，在 Mnemox 当前真实架构目标下，它们没有同时满足“正确性 + 性能/能力净收益 + 运维成本”门槛。

产品继续：

```text
SQLite / PostgreSQL = 规范数据源
SqlGraphStore         = 产品图查询
Chroma                = 可重建向量投影
Sparse FTS            = 可重建关键词投影
Neo4j / Graphiti      = 不进入默认产品 runtime
```

Stage 6 收口点的 `create_graph_store()` 保持只返回 `SqlGraphStore`，以证明当时不会因为候选 flag 误开而切流。后续 Stage 7 若实现 `GRAPH_BACKEND=neo4j`，必须通过新的显式 backend 配置、健康检查、fallback 和灰度契约进入，不能复用模糊的 `*_ENABLED` 语义偷偷切换。

---

## 2. Neo4j 最终证据

### 2.1 已通过的门禁

- 官方 Python Driver 6.3.x；真实 Neo4j 5.26 Community 集成通过。
- Docker Compose 仅 `graph-shadow` profile 启动；默认部署不增加 Neo4j。
- 固定参数化 Cypher；无 Text2Cypher。
- 节点/关系显式 `user_id` 范围过滤。
- Neo4j 投影不保存 Claim statement、Evidence excerpt、Unit text 等正文。
- 可按用户全量 rebuild；来源删除后可清理。
- `neo4j_graph` 独立 outbox target；不会误消费 Chroma backlog。
- 失败使用现有 retry / DLQ；认证失败不会污染 canonical SQL transaction。
- Shadow diff 不改变 Association V2 用户结果。
- 1000 / 5000 Claim 合成图：ID/path/score 一致率均为 `1.0`；跨用户命中与正文属性泄漏均为 `0`。
- projection lag 已可量化：pending backlog age、processed lag、DLQ count 均有无正文诊断。

### 2.2 稳态性能

30 个 anchor、固定当前 SQL 候选预算语义：

| 规模 | Probe | SQL p95 | Neo4j p95 | SQL/Neo4j |
| --- | --- | ---: | ---: | ---: |
| 1,000 Claim | direct | 16.918 ms | 19.393 ms | 0.872x |
| 1,000 Claim | shared | 12.084 ms | 8.905 ms | 1.357x |
| 1,000 Claim | combined | 29.195 ms | 25.010 ms | 1.167x |
| 5,000 Claim | direct | 23.706 ms | 25.766 ms | 0.920x |
| 5,000 Claim | shared | 23.087 ms | 16.742 ms | 1.379x |
| 5,000 Claim | combined | 33.969 ms | 19.199 ms | 1.769x |

结论不是“Neo4j 没有任何性能价值”：较大图的 shared/combined 确实更快。

但 direct path 没有稳定收益；1000 Claim combined 仅约 17% 改善。当前 Association 主链整体还包含 Sparse、Evidence hydration、reranker/Judge 等阶段，单个图 probe 的几十毫秒改善不足以自动证明产品净收益。

### 2.3 资源/运维成本

Stage 6 临时容器在本轮不同负载阶段观察到约：

- Neo4j 内存：约 `0.7–1.0 GiB`；
- `/data`：约 `0.52 GiB`；
- 新增常驻服务、凭据、备份、恢复、版本升级、监控与告警面；
- Windows/桌面模式仍不能要求用户安装 Neo4j，因此 SQL backend 无论如何必须长期保留。

### 2.4 Neo4j NO-GO 原因

第 10.5 节的强制门槛要求“2～4 跳查询性能**或实现维护性有明确净收益**”以及“生产部署、备份、恢复、凭据、资源和监控通过验收”。

当前：

- 正确性门禁：通过；
- 安全/隔离门禁：通过；
- rebuild/delete/fallback：通过；
- 性能：部分 query shape 有收益，部分无收益；
- 运维/资源：相对 SQL 明显新增成本；
- 桌面端：仍必须保留 SQL；
- 没有证据表明增加 Neo4j 后 Association 产品质量提高。

因此当前 **NO-GO**。不为“已经写了 Neo4jGraphStore”而人为进入 Stage 7。

---

## 3. Graphiti 最终证据

### 3.1 已通过的门禁

- `graphiti-core 0.30.1` 为独立 spike 依赖，不进入默认 requirements。
- 初始化前强制 `GRAPHITI_TELEMETRY_ENABLED=false`。
- `store_raw_episode_content=False`。
- Graphiti `group_id` 已改为 0.30.x 合法格式 `mnemox_user_<id>`；旧的冒号格式在真实 `search()` 中会被 SDK 拒绝，Stage 6 已通过真实集成发现并修复。
- Claim 摄入只允许：当前用户、confirmed、active Claim、current Revision、active Source、有 Evidence。
- Temporal 摄入只允许 reviewed declaration：`confirmed / superseded / expired`；staged/ignored/inaccurate 和其他用户不摄入。
- 来源 Revision supersede 后旧 Claim 不再 rebuild 进入 Graphiti。
- 新增 temporal search boundary：
  - 强制单用户 group；
  - 支持 as-of；
  - 依据 Graphiti edge `valid_at / invalid_at / expired_at` 再过滤；
  - 只从 deterministic episode UUID 映射回 canonical SQL `MemoryDeclaration.id`；
  - raw fact/query 不进入 Shadow diagnostics。
- Graphiti 搜索异常只返回 error type，不记录 query/body，SQL transaction 保持可用。
- 真实 Graphiti 0.30.1 + Neo4j BM25-only 搜索集成通过。

### 3.2 一个重要的真实 SDK 约束

Graphiti 0.30.1 即使只运行 BM25-only 测试，`EntityNode.save()` / `EntityEdge.save()` 的 Neo4j 保存路径仍要求 vector property 非空。

Stage 6 为了保证 **0 外部模型调用**，使用本地固定 1024 维零向量作为测试占位。任何 LLM / embedder / cross-encoder 调用都由官方基类的阻断 stub 立即报错。

因此可以明确区分：

- Graphiti 图搜索层本身可以零模型运行；
- 但其数据模型和正常高层 `add_episode` 路径天然围绕 embedding/LLM 设计；
- 真正使用 Graphiti 的时态抽取能力会引入额外模型调用，而 Mnemox 当前已经在 SQL 中拥有审计过的事实身份、冲突审核和有效期。

### 3.3 SQL vs Graphiti BM25

使用同一组 synthetic confirmed memory facts、同一唯一 token query、30 个 query，保证两侧 Recall@5 都为 `1.0`：

| Temporal facts | SQL p95 | Graphiti BM25 p95 | Recall@5 | 外部模型调用 |
| ---: | ---: | ---: | --- | ---: |
| 100 | 8.281 ms | 14.242 ms | SQL `1.0` / Graphiti `1.0` | 0 |
| 1,000 | 9.616 ms | 19.147 ms | SQL `1.0` / Graphiti `1.0` | 0 |

Graphiti seed：

- 100 facts：约 246 ms；
- 1,000 facts：约 1.41 s。

当前 benchmark 的 Graphiti 是其**最低成本形态**：BM25-only、无模型调用。即便如此，在 Mnemox 已有结构化 Temporal SQL 的同义检索问题上，它约为 SQL p95 的 1.7～2.0 倍。

### 3.4 Graphiti NO-GO 原因

Mnemox 当前 Temporal SQL 已有：

- `user_id + fact_key` 事实身份；
- 当前 confirmed 事实部分唯一约束；
- staged conflict；
- 用户确认替代；
- `valid_from / valid_to`；
- superseded / expired；
- 来源和审计历史；
- 全产品入口的过期过滤。

Graphiti 的零模型 BM25 搜索没有性能净收益；要获得其真正的语义/时态抽取能力，则必须再引入 LLM/embedding/reranker 调用和底层图服务资源，同时不能替代 canonical SQL 的审核与事务约束。

因此没有必要为了“时态图”重复维护同一事实体系。

Graphiti 当前 **NO-GO**。

由于候选已经在“净收益”强制门槛失败，Stage 6 按 stop rule **不再使用真实用户数据或付费外部模型继续扩大评测**。这不是缺失验收，而是候选提前失败后避免增加隐私暴露和无必要成本。

---

## 4. Stage 6 最终门禁

| 门禁 | Neo4j | Graphiti |
| --- | --- | --- |
| 用户隔离 | PASS | PASS |
| 删除/版本失效 | PASS | PASS |
| 可重建 | PASS | PASS（group rebuild） |
| 故障不影响 SQL | PASS | PASS |
| Shadow 不改变用户结果 | PASS | PASS（仅 evaluator） |
| 正文/查询不进入 diagnostics | PASS | PASS |
| 目标功能正确性 | PASS | PASS |
| 明确性能/能力净收益 | **FAIL** | **FAIL** |
| 资源/运维净收益 | **FAIL** | **FAIL** |
| 值得进入生产灰度 | **NO** | **NO** |

**Stage 6 完成方式：两个候选均 NO-GO。**

---

## 5. Stage 7 处理

当前 Neo4j / Graphiti 候选没有 go ADR，因此：

- 不开启 `NEO4J_GRAPH_ENABLED` 产品切流；
- 不开启 `GRAPHITI_ENABLED` 产品切流；
- 不新增桌面 Neo4j 依赖；
- 不把 Graphiti 加入正常知识/记忆写入；
- `SqlGraphStore` 保持唯一产品 GraphStore；
- Temporal SQL 保持唯一事实/冲突/有效期权威。

这是 Stage 6 在“是否默认产品切流”这个问题上的收口结论：当时不进入 Stage 7 默认图迁移。随后同日新增的双目标 ADR 将 Stage 7 重新定义为 **Optional Neo4j Backend + Graphiti Temporal/Episodic Slice**，因此本段不再解释为“永久停止实现”，而应解释为“禁止无证据的默认切流”。

---

## 6. 未来重新评估的触发条件

只有出现新的产品证据时重新打开，而不是定期重试：

### Neo4j

至少满足其一：

- 单用户真实图稳定达到数万～十万 Claim/Relation，SQL 2～4 hop p95 明显超过产品预算；
- 需要的图算法/路径能力已经无法用可维护 SQL 实现；
- Neo4j 能带来可测的 Association 质量提升，而不只是 Cypher 可读性；
- 部署形态已经天然拥有受管图服务，常驻资源/备份成本不再是主要负担。

### Graphiti

至少满足其一：

- 真实用户出现大量“自然语言查询历史事实在某个时间点的状态”需求，现有 Temporal SQL + RetrievalRouter 质量明显不足；
- 有匿名真实集证明 Graphiti 在该场景 Recall/NDCG 有显著提升；
- 能复用现有 Mnemox Provider/Embedding 成本治理，不形成第二套隐式模型账单；
- 隐私和删除语义能够与 SQL 审计严格对齐。

在这些触发条件出现前，NO-GO 结论保持有效。
