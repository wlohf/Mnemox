# Mnemox V2：图基础设施提前建设与运行时延迟引入策略

> 日期：2026-09-04
> 状态：当前有效
> 原始决策：**Architecture READY / Runtime DEFERRED**
> 2026-09-04 补充决策：在保持默认产品 Runtime 不变的前提下，Neo4j 重新打开为 **Optional Graph Backend** 建设目标，Graphiti 重新打开为独立 **Temporal/Episodic Vertical Slice**。原因不是推翻 Stage 6 性能结论，而是 Mnemox 同时承担产品、技术学习与工程作品集目标。最新实施依据见 [图架构演进、技术选型与作品集目标决策](2026-09-04-mnemox-v2-graph-evolution-and-portfolio-architecture.md)。
> 目标窗口：正式上线前约 2～4 周，用于把图架构做深、做可运行、做可验证，而不是把所有候选组件变成默认依赖。

## 1. 背景与真正的问题

Mnemox 的长期方向天然会越来越“图化”：

- Claim 与 Claim 之间存在支持、反驳、解释、示例等关系；
- Claim 与 Concept 之间存在语义归属；
- Concept 之间存在先修、相关、层级等关系；
- Source、Evidence、Memory、Goal、Skill、Learning State 后续也可能参与路径与推理；
- 产品会逐渐出现“为什么相关”“从当前知识到目标知识缺什么”“多跳关联”“学习路径”等图查询。

因此真正的问题不是：

> SQL 能不能实现知识图谱？

而是：

> 我们是否正在为了暂时不引入 Neo4j / Graphiti，而用越来越复杂的 SQL 与 Python 重复实现图数据库或时态知识框架已经解决的问题？

同时也要避免另一个极端：为了未来可能出现的复杂度，在只有少量用户和固定查询形态时就正式承担 Neo4j / Graphiti 的部署、同步、备份、监控和双后端一致性成本。

本 ADR 将这两个问题拆开：

1. **图架构和数据模型要提前准备。**
2. **图运行时是否启用，要等复杂度和收益达到门槛。**

---

## 2. 当前代码现实：目前还没有明显“为了 SQL 而造轮子”

截至 2026-09-04，相关实现大致规模：

```text
SqlGraphStore                 ~197 LOC
Neo4jGraphStore               ~597 LOC
GraphitiShadowAdapter         ~350 LOC
Association V2                ~383 LOC
```

行数不是架构优劣的唯一指标，但它说明当前阶段一个重要事实：

> 对 Mnemox 目前只有少量、固定、1～3 hop 的图查询，SQL 版本仍然是更小、更直接的实现；正式引入 Neo4j / Graphiti 并不会自动让系统总代码更少。

原因是 Neo4j / Graphiti 不只带来查询语法，还会带来：

- Canonical SQL → Graph projection；
- outbox / worker；
- projection lag；
- rebuild；
- source delete；
- 用户隔离；
- 连接管理；
- schema / index；
- credential；
- backup / restore；
- 版本升级；
- Shadow diff；
- fallback；
- 桌面 SQLite 模式的双实现。

因此当前 Stage 6 的 No-Go 不是“SQL 比图数据库高级”，而是：

> **当前图查询复杂度还没有高到足以抵消第二套运行时的工程成本。**

---

## 3. 但禁止继续“硬写 SQL”直到失控

Architecture READY / Runtime DEFERRED 不代表未来一直优先 SQL。

一旦出现下面的趋势，就说明 `SqlGraphStore` 正在开始重复实现图引擎能力：

- 自己维护越来越多 `frontier / visited / depth`；
- 多处重复 BFS / DFS；
- 大量递归 CTE；
- 为每一种关系组合手写特殊查询；
- 自己拼接和恢复完整 path；
- 自己实现 shortest path；
- 自己实现 weighted path / k-shortest-path；
- 自己实现 community / centrality / PageRank；
- 查询关系类型和 hop 数开始由业务动态决定；
- 代码复杂度主要来自“如何走图”，而不是业务规则本身。

出现这些情况时，继续扩展 SQL 不是“控制依赖”，而是在重复造图数据库的轮子。

**原则：当业务问题已经变成图算法问题时，使用图引擎，而不是继续扩写关系 SQL。**

---

## 4. Neo4j 与 Graphiti 必须分开判断

### 4.1 Neo4j：未来图执行引擎候选

Neo4j 解决的核心问题是：

> 节点、关系、路径、多跳遍历和图算法成为一等公民。

它最可能替代的是：

```text
SqlGraphStore
    ↓
Neo4jGraphStore
```

而不是替代 PostgreSQL 作为规范事实库。

长期推荐架构：

```text
PostgreSQL / SQLite
Canonical Knowledge
        │
        ├── Chroma / Dense Projection
        ├── Sparse FTS Projection
        └── Graph Projection
                │
                └── Neo4jGraphStore（达到门槛后启用）
```

因此 Neo4j 当前应视为：

> **Runtime NO-GO，Architecture READY。**

### 4.2 Graphiti：不是简单“换查询引擎”

Graphiti 解决的问题更接近：

```text
Episode
  ↓
LLM / Entity / Fact extraction
  ↓
Temporal Fact Graph
  ↓
Invalidation / Search
```

而 Mnemox 已经拥有：

- Claim / Evidence；
- MemoryDeclaration；
- fact_key；
- confirmed / staged / superseded / expired；
- conflicts_with；
- supersedes；
- valid_from / valid_to；
- 人工审核和来源生命周期。

因此 Graphiti 与当前领域模型重叠比 Neo4j 大得多。

Graphiti 只有在未来出现以下明确缺口时重新评估：

- 大量自由聊天 / Episode 需要自动形成时态事实；
- 自定义 Entity / Fact 抽取与失效代码快速膨胀；
- SQL Temporal Memory 无法自然表达跨 Episode 的动态关系；
- Graphiti 在真实数据上能减少显著工程代码，同时不破坏 Mnemox 的审核、证据和权限边界。

否则优先“借鉴 Graphiti 的思想”，而不是同时维护两套 Temporal Fact System。

---

## 5. 上线前 2～4 周应该提前做好的“地基”

当前没有非常紧急的 deadline，因此可以主动做基础架构收口，但目标不是把未来所有运行时都部署出来。

### A. 图领域模型先稳定

明确并文档化：

- 哪些对象是 Node；
- 哪些关系是 Edge；
- Edge 的方向；
- Relation type 的语义；
- 哪些关系必须带 Evidence；
- 哪些关系可以自动产生；
- 哪些关系必须人工确认；
- Relation 生命周期和来源版本规则；
- Temporal 属性属于 Canonical Fact 还是 Projection。

迁移数据库不难，迁移一个错误的领域模型才最贵。

### B. GraphStore 保持存储无关

业务层不得依赖 SQLAlchemy / Cypher 细节。

业务只表达：

- 从 Claim 扩展关联 Claim；
- 从 Concept 扩展结构；
- 查询来源 Claim；
- 取得可解释 path；
- depth / limit / pattern 等业务约束。

未来切到 Neo4j 应主要是“替换 GraphStore 实现”，而不是修改 Association / Router / UI。

### C. 保持 Canonical / Projection 分层

```text
用户写入
  ↓
Canonical SQL
  ↓
Transactional Outbox
  ↓
Rebuildable Projections
```

Neo4j、Chroma、Sparse 都不得成为无法重建的唯一事实来源。

### D. 保留 Shadow / Diff / Rebuild 能力

未来重新评估 Neo4j 时，不从零开始：

```text
SqlGraphStore → 用户正式结果
Neo4jGraphStore → Shadow
                 ↓
           latency / parity / path diff
```

真实数据证明收益后才切流。

### E. 增加“禁止造图引擎”的架构门禁

Code review / roadmap 每次增加 GraphStore 能力时都要问：

> 这是 Mnemox 特有的业务规则，还是通用图遍历 / 图算法？

如果主要是后者，应暂停继续扩展 SQL，并重新评估 Neo4j。

---

## 6. Neo4j 重新启用触发条件

不单纯按用户数决定。满足下列任意 **2～3 项** 时，重新进入 Neo4j Shadow：

1. 常见图查询超过 3 hop；
2. 业务开始需要动态组合 Relation type；
3. 需要 shortest path / weighted path；
4. 需要 community / centrality / PageRank / connected components；
5. `SqlGraphStore` 出现多处重复 BFS / recursive CTE / path reconstruction；
6. 为新增一种关联模式需要修改多个固定 SQL 特例；
7. Graph 查询 p95 达不到产品目标；
8. 图规模达到真实 50k～100k+ Claim/Concept 后 SQL 遍历明显退化；
9. 图查询逻辑成为 Association / Learning Path 的主要开发复杂度来源；
10. Neo4j 在真实数据上的综合收益足以覆盖投影和运维成本。

其中第 5、6、9 项尤其重要：

> **代码复杂度本身就是切换信号，不必等性能先出问题。**

---

## 7. Graphiti 重新评估触发条件

满足以下条件时才重新进入 Graphiti Spike：

1. Conversation / Episode 成为主要知识来源；
2. 自动时态 Fact extraction 的自研代码明显增长；
3. 需要大量实体状态随时间变化的自动推断；
4. MemoryDeclaration 只能通过越来越多特殊 case 才能表达需求；
5. Graphiti 能在真实匿名数据上显著减少代码和模型调用总成本；
6. 能继续保证 Evidence、review、conflict、privacy、delete 和 Canonical SQL 权威性。

Graphiti 不因“系统越来越图化”自动启用；它解决的是 Temporal/Episodic Knowledge 问题，而不是所有 Graph 问题。

---

## 8. 防止两个极端

### 极端 A：亡羊补牢

```text
所有关系都先塞 SQL
→ SQL 越写越复杂
→ 用户上线后性能/维护崩掉
→ 临时迁 Neo4j
```

禁止。

### 极端 B：过度设计

```text
只有少量固定 1～3 hop 查询
→ 立即部署 PostgreSQL + Chroma + Neo4j + Graphiti
→ 大量时间花在同步、监控、备份和一致性
→ 产品价值还没有真人验证
```

同样禁止。

正确路线：

```text
图模型提前设计
GraphStore 抽象稳定
Projection / Outbox / Shadow / Rebuild 提前具备
        ↓
SQL 承担当前简单图查询
        ↓
持续观察复杂度阈值
        ↓
一旦开始“造图引擎”
        ↓
Neo4j Shadow → 真实数据验证 → 切流
```

---

## 9. 当前最终决策

### Neo4j

```text
默认 Runtime：        仍不启用
可选 Runtime：        进入建设
架构接口：            保留并扩展为真正可切换 Graph Backend
Projection / Shadow： 保留并继续作为上线前验证手段
核心新增能力：        Knowledge / Learning Path、Explainable Multi-hop
Canonical：           PostgreSQL / SQLite
```

### Graphiti

```text
默认 Runtime：        仍不启用
独立 Vertical Slice： 进入建设
Temporal SQL：        继续作为 Canonical
核心场景：            Episode → Temporal Fact → as-of / invalidation
边界：                不直接替代 MemoryDeclaration
```

### 上线前原则

未来 2～4 周优先把“承重结构”做好：

1. 图领域模型；
2. GraphStore 边界；
3. Canonical / Projection 契约；
4. Outbox / Rebuild / Shadow；
5. 架构复杂度触发门槛；
6. 真实匿名语料与真人 Association 验收。

**不以“现在查询还快”为理由无限扩写 SQL，也不以“未来一定图化”为理由提前承担全部 Neo4j / Graphiti 运行时成本。**
