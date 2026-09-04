# Mnemox V2：图架构演进、技术选型与作品集目标决策

> 日期：2026-09-04
> 状态：**当前有效**
> 决策：**PostgreSQL / SQLite 保持 Canonical；Neo4j 从 Shadow 候选升级为“可选正式 Graph Backend”建设目标；Graphiti 作为独立 Temporal/Episodic Vertical Slice 建设，不替代现有 Temporal SQL。**
> 目标窗口：正式上线前约 2～4 周。

---

## 1. 为什么重新打开这个决策

Stage 6 已经完成 Neo4j / Graphiti 的真实 Shadow 验证，并得出“双 Runtime NO-GO”：

- 当前 1～3 hop、固定 Relation pattern 下，`SqlGraphStore` 足够快且实现更小；
- Neo4j 在 5,000 Claim 的 shared / combined multi-hop 上有性能优势，但 direct query 没有稳定优势；
- Graphiti BM25-only 在相同 Recall 下慢于现有 Temporal SQL；
- 如果只以“当前产品运行成本 / 当前查询性能”衡量，暂时不默认启用二者是合理结论。

这个结论仍然有效。

但 Mnemox 还有第二个明确目标：

> 它不仅要成为可上线的学习产品，也要成为能够系统展示 AI Application / Agent / RAG / Knowledge Graph / Memory 工程能力的长期技术项目。

在 AI Coding 显著降低实现成本后，2～4 周不再只能完成少量功能。此时技术选型不能只优化“最小运行时依赖”，还要考虑：

1. 能否用真实产品问题学习并验证目标技术；
2. 能否形成可量化、可解释的架构演进过程；
3. 能否在面试中说明为什么用、为什么不用、什么时候切换，而不是只列技术栈；
4. 是否能避免为了使用新技术而破坏已有正确的领域模型和数据权威边界。

因此，本决策不是推翻 Stage 6，而是改变下一阶段的优化目标：

```text
Stage 6 的问题：
“现在是否值得把 Neo4j / Graphiti 作为默认产品 Runtime？”
答案：No。

本阶段的问题：
“在保持产品默认路径简单稳定的前提下，是否值得把 Neo4j / Graphiti 做成真实、可运行、可解释、可演示的技术能力？”
答案：Yes，但二者采用不同策略。
```

---

## 2. Mnemox 的图架构演进故事

这段演进必须长期保留，因为它既是架构依据，也是后续学习和面试复盘的主线。

### 阶段 A：先建立 Canonical SQL

Mnemox 最初需要解决的不是图数据库问题，而是知识事实是否可信：

```text
Source
  ↓
Revision
  ↓
KnowledgeUnit
  ↓
Claim
  ↓
Evidence
```

以及：

```text
Claim ↔ Concept
Claim ↔ ClaimRelation
Concept ↔ ConceptEdge
```

PostgreSQL / SQLite 最适合承担：

- 事务；
- 用户隔离；
- 审核状态；
- Evidence；
- 来源版本；
- 删除和失效；
- 唯一约束；
- Temporal fact lifecycle。

所以 SQL 先成为 **Canonical Source of Truth**。

这不是“没想到 Neo4j”，而是先解决数据正确性和业务约束。

### 阶段 B：图查询先用 `SqlGraphStore`

早期只有少量固定图查询：

- shared concept；
- direct claim relation；
- concept structure；
- personal evidence by concept；
- 1～3 hop；
- Relation pattern 基本固定。

因此抽象：

```text
GraphStore
    ↓
SqlGraphStore
```

让业务层只认识图语义，不认识 SQLAlchemy。

这一步解决的是：

> “先让领域服务依赖图接口，而不是依赖某个图数据库。”

### 阶段 C：Transactional Outbox + Neo4j Shadow

随着 Claim / Concept 图真实存在，引入：

```text
Canonical SQL
    ↓
Transactional Outbox
    ↓
Neo4j Projection
```

并实现：

```text
SqlGraphStore   → 正式结果
Neo4jGraphStore → Shadow 结果
                  ↓
             ID / Path / Score Diff
```

Stage 6 实测证明：

- 1,000 / 5,000 Claim 下 ID / Path / Score parity = 100%；
- 跨用户泄漏 = 0；
- 禁止原文属性泄漏 = 0；
- 5,000 Claim combined p95：SQL 约 `33.97 ms`，Neo4j 约 `19.20 ms`；
- direct p95：SQL 约 `23.71 ms`，Neo4j 约 `25.77 ms`。

因此没有盲目切流。

### 阶段 D：现在进入“可选 Graph Backend + Graph-native Feature”

接下来不是把 SQL 删除，而是把架构变成：

```text
                    Canonical Knowledge
                 PostgreSQL / SQLite
                         │
            Transactional Outbox
                         │
       ┌─────────────────┼─────────────────┐
       ↓                 ↓                 ↓
   Sparse FTS          Chroma        Neo4j Projection
   keyword             dense               │
       │                 │                 ↓
       │                 │           Neo4jGraphStore
       │                 │                 │
       └─────────────────┼─────────────────┘
                         ↓
                  Retrieval / Graph
                         ↓
                    Association
```

Graph backend：

```text
GRAPH_BACKEND=sql       # 默认 / desktop fallback
GRAPH_BACKEND=neo4j     # 可选 server backend
```

这一步的目标不是“Neo4j 一定比 SQL 快”，而是：

> 当产品开始需要真正的路径、多跳和图算法时，有一个已经验证过的图执行引擎，而不是继续让 `SqlGraphStore` 变成自研图引擎。

### 阶段 E：Graphiti 独立 Temporal / Episodic Slice

Graphiti 不直接替换 `MemoryDeclaration`。

目标是验证：

```text
Episode
  ↓
Temporal Fact / Entity Graph
  ↓
valid_at / invalid_at
  ↓
historical search
```

是否能为未来的：

- Conversation memory；
- learning episode；
- evolving user goal；
- evolving project / preference / state；

提供明显价值。

Mnemox Temporal SQL 继续是权威事实系统。

---

## 3. 为什么 Neo4j 值得继续做

### 3.1 不是为了“简历上有 Neo4j”

禁止这种实现：

```text
安装 Neo4j
→ 写两个节点
→ README 写“使用 Neo4j”
```

这种没有工程价值，也没有面试区分度。

真正要做的是让 Neo4j 解决它擅长的问题：

- multi-hop traversal；
- explainable path；
- shortest path；
- dynamic relation combination；
- future graph algorithms。

### 3.2 代码复杂度也是切换指标

未来不需要等 SQL 性能先坏掉。

如果出现：

- 重复 `frontier / visited / depth`；
- BFS / DFS；
- recursive CTE；
- path reconstruction；
- shortest path；
- dynamic edge combination；
- community / centrality / PageRank；

就说明业务问题已经是 Graph Problem。

此时继续硬写 SQL 是重复造轮子。

### 3.3 Neo4j 在 Mnemox 中的正确角色

不是：

```text
Neo4j = Knowledge Truth
```

而是：

```text
SQL = Canonical Truth
Neo4j = Graph Execution / Projection
```

这样：

- Neo4j 可删可重建；
- SQLite desktop 仍能工作；
- Neo4j 故障可 fallback；
- 业务审核和 Evidence 不被图数据库绑死；
- 未来可以继续更换图引擎。

---

## 4. Neo4j 必须承载至少一个真正 Graph-native 的产品能力

仅把现有 1-hop SQL 查询翻译成 Cypher，不足以证明采用价值。

### 第一目标：Knowledge / Learning Path

示例：

```text
用户当前掌握：Tool Calling
目标：LangGraph
```

系统寻找：

```text
Tool Calling
    ↓ prerequisite / related
Agent Runtime
    ↓
State Management
    ↓
Workflow
    ↓
LangGraph
```

然后输出：

- 推荐路径；
- 中间缺失 Concept；
- 每一步为什么需要；
- 对应 Claim / Evidence / Material；
- 用户已经掌握 / 未掌握的节点。

它自然涉及：

- path search；
- depth；
- prerequisite graph；
- user mastery overlay；
- explainability。

这是 Neo4j 比“单纯换数据库”更有意义的使用场景。

### 第二目标：Explainable Multi-hop Association

用户看到一个联想结果时，不只显示：

```text
A 与 B 相关
```

而是展示：

```text
当前 Claim
  ↓ about
Tool Calling
  ↓ prerequisite_of
Agent Runtime
  ↓ discussed_in
目标资料 / Claim
```

也就是回答：

> “为什么系统认为它和当前知识相关？”

### Stretch：Graph Analytics

只有前两项稳定后，再选择一个：

- bridge concept；
- central concept；
- knowledge community；
- disconnected knowledge island。

不在第一轮同时实现全部图算法。

---

## 5. 为什么 Graphiti 也值得做，但方式不同

Graphiti 的价值不是 Graph Query，而是：

> 把持续发生的 Episode 转成随时间变化的事实和关系。

例如：

```text
Sep 01: 用户正在学习 Tool Calling
Sep 10: Tool Calling 已完成，开始 Agent Runtime
Sep 20: 开始 LangGraph
```

可形成：

```text
learning_focus = Tool Calling
valid: Sep 01 → Sep 10

learning_focus = Agent Runtime
valid: Sep 10 → Sep 20

learning_focus = LangGraph
valid: Sep 20 → current
```

然后回答：

- “9 月 12 日我在学什么？”
- “最近一个月学习重点如何变化？”
- “哪个旧目标已经失效？”

### 为什么不直接替代 Temporal SQL

因为 Mnemox 已经有：

- `MemoryDeclaration`；
- `fact_key`；
- `valid_from / valid_to`；
- `confirmed / staged / superseded / expired`；
- `conflicts_with / supersedes`；
- Evidence / review / source lifecycle。

如果 Graphiti 直接接管，会形成两套事实权威。

因此采用：

```text
Temporal SQL = Canonical
Graphiti      = Optional Temporal Graph Projection / Experiment
```

只有真实 Episode 需求证明 Graphiti 能减少大量自研代码后，再讨论扩大职责。

---

## 6. 技术选型不是“谁更强”，而是职责分工

| 技术 | Mnemox 中的职责 | 为什么用 | 为什么不让它包办 |
| --- | --- | --- | --- |
| PostgreSQL / SQLite | Canonical Knowledge / Transaction / Review / Evidence / Temporal Truth | 强事务、约束、审计、成熟 | 路径和图算法不是其最自然领域 |
| Chroma | Dense semantic retrieval | 向量语义召回简单直接 | 不是事实库，也不擅长图关系 |
| FTS5 / PostgreSQL FTS | Sparse lexical retrieval | 快、便宜、可解释 | 不解决语义和路径 |
| Neo4j | Graph traversal / path / graph-native feature | 节点、边、路径、图算法一等公民 | 增加第二数据库与投影运维成本 |
| Graphiti | Temporal / Episodic graph experiment | Episode→Fact→Temporal relation 有完整框架 | 与现有 Temporal SQL 领域模型高度重叠 |

最终不是“选择一个万能数据库”，而是：

```text
Canonical + Specialized Projections
```

---

## 7. 面试时应该怎么解释这段架构演进

### 7.1 30 秒版本

> Mnemox 的知识层最初用 PostgreSQL 存 Claim、Concept、Evidence 和 Relation，因为早期只有固定的 1～3 hop 查询，SQL 更简单也更快。后来我抽象了 GraphStore，通过 Transactional Outbox 把 Canonical SQL 投影到 Neo4j，并做 SQL / Neo4j Shadow，对 ID、Path、Score 做一致性验证。5,000 Claim 下 combined multi-hop p95 从约 34ms 降到约 19ms，但 direct query 没有优势，所以没有盲目切换。后续因为产品开始需要 Knowledge Path、Shortest Path 和可解释多跳关系，我把 Neo4j 做成可选 Graph Backend，而 PostgreSQL 仍然负责事实、Evidence、审核和事务。

### 7.2 为什么这个回答比“我用了 Neo4j”更重要

它证明你理解：

- relational vs graph data model；
- Canonical / Projection；
- CQRS 思想；
- Transactional Outbox；
- eventual consistency；
- graph traversal；
- Shadow traffic；
- correctness parity；
- benchmark；
- fallback；
- 技术选型 trade-off。

### 7.3 Graphiti 面试版本

> Mnemox 已经有 SQL Temporal Memory，所以我没有直接让 Graphiti 接管 Memory，而是把它作为 Episodic Temporal Graph 做独立验证。我比较了 valid/invalid/as-of 查询、用户隔离和检索延迟，发现当前结构化 MemoryDeclaration 用 SQL 更简单。因此保留 SQL 为 Canonical，只在自由 Episode 自动知识形成场景使用 Graphiti。这个设计避免两套事实系统互相争夺权威。

---

## 8. 学习时必须真正掌握的知识点

### Neo4j / Knowledge Graph

不能只会写 Cypher，需要掌握：

1. Property Graph 模型；
2. Node / Relationship / Property；
3. Cypher MATCH / OPTIONAL MATCH / variable-length path；
4. index / constraint；
5. traversal 与 relational JOIN 的区别；
6. shortest path；
7. graph projection；
8. user-scoped graph isolation；
9. eventual consistency；
10. outbox / rebuild / fallback；
11. graph query benchmark；
12. 图算法适用条件。

### Graphiti / Temporal Memory

需要掌握：

1. Episode；
2. Entity / Fact / Edge；
3. `valid_at / invalid_at`；
4. Temporal fact invalidation；
5. Episode 到结构化事实的抽取；
6. as-of query；
7. Temporal SQL 与 Temporal Graph 的区别；
8. LLM / embedding cost；
9. privacy / deletion；
10. Canonical truth 与 derived graph 的边界。

---

## 9. 防止为了作品集而过度设计

学习 / 求职目标是合法的工程收益，但不能成为乱堆技术的理由。

禁止：

- 为了写进简历而让 Neo4j 成为唯一事实库；
- 为了 Graphiti 删除已经稳定的 `MemoryDeclaration`；
- 同时实现五种图算法但没有产品入口；
- 不做 benchmark 就宣称 Neo4j 更快；
- 不做用户隔离和删除就展示 Demo；
- 只写 README，不做真实可运行路径；
- 为了“技术多”而牺牲 Windows / SQLite desktop fallback。

原则：

> **每引入一个技术，都必须对应一个真实问题、一个可运行模块、一组可量化证据和一段可以解释 trade-off 的架构故事。**

---

## 10. 最终决策

### 产品默认路径

```text
PostgreSQL / SQLite + Chroma + Sparse + SqlGraphStore
```

保持稳定，不因为作品集目标强制所有部署启用 Neo4j / Graphiti。

### Neo4j

```text
状态：从 Shadow Spike 升级为 Optional Graph Backend 建设目标
用途：Graph-native traversal / Knowledge Path / Explainable Multi-hop
默认：关闭
Canonical：SQL
必须支持：fallback / rebuild / health / lag / parity
```

### Graphiti

```text
状态：独立 Temporal/Episodic Vertical Slice
用途：Episode → Temporal Fact Graph → historical query
默认：关闭
Canonical：Temporal SQL
不得直接取代 MemoryDeclaration
```

### 下一步

实施顺序以：

`docs/superpowers/plans/2026-09-04-mnemox-v2-neo4j-graphiti-implementation-plan.md`

为准。

---

## 11. 后续统一的“技术选型 / 面试解释模板”

以后复盘 Mnemox 中任何重要技术，不只说“它是什么”，统一按下面顺序解释和记录：

1. **背景 / 痛点**：原来系统是什么样，遇到了什么真实问题？
2. **为什么旧方案一开始是合理的**：避免事后诸葛亮式地否定早期架构。
3. **什么时候开始不够用**：性能、能力、代码复杂度、运维还是产品需求发生了什么变化？
4. **为什么选择这个技术**：它具体比旧方案自然在哪里？
5. **为什么不选其他候选**：至少说明 1～2 个替代方案及 trade-off。
6. **在 Mnemox 中怎么落地**：数据流、接口、Canonical / Projection、失败路径、用户隔离。
7. **真实证据**：Benchmark、Recall、p50/p95、测试、资源、故障注入，而不是主观判断。
8. **代价是什么**：复杂度、部署、同步、成本、隐私、迁移和维护面。
9. **最终职责边界**：这个技术负责什么、不负责什么。
10. **如果重新做一次会怎么选**：说明当前结论成立的前提，以及未来什么信号会再次演进。

面试叙事可以压缩为：

```text
Problem
  → Why the original design made sense
  → New pressure / limitation
  → Candidate comparison
  → Architecture decision
  → Implementation
  → Measured evidence
  → Trade-off
  → Current boundary
  → Future evolution trigger
```

这套模板同时适用于 Neo4j、Graphiti、Chroma、Qdrant、LangGraph、FSRS、Reranker、Agent Runtime 等后续技术决策。
