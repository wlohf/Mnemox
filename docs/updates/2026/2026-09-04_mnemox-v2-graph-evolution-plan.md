# Mnemox V2：图架构演进与 Stage 7 重新打开

> 日期：2026-09-04
> 类型：架构 / 路线图更新
> 本轮不修改产品运行代码。

## 背景

Stage 6 已完成 Neo4j / Graphiti 的真实 Shadow 验证，并得出“默认产品 Runtime 双 NO-GO”。该结论只回答当前规模下是否值得默认切流，并不代表相关技术没有长期价值。

新的项目目标进一步明确：Mnemox 同时承担产品、系统学习和工程作品集职责。由于 AI Coding 显著降低实现成本，正式上线前约 2～4 周可以主动把目标技术做成真实、可运行、可解释的工程模块，而不是只停留在 Spike。

## 本轮决策

### Neo4j

从：

```text
Shadow-only candidate
```

调整为：

```text
Optional Graph Backend target
```

但保持：

```text
PostgreSQL / SQLite = Canonical
SqlGraphStore        = default / desktop fallback
Neo4jGraphStore      = optional server backend
```

Neo4j 必须承载真正 graph-native 的能力，而不是只把已有 SQL 翻译成 Cypher：

1. Knowledge / Learning Path；
2. Explainable Multi-hop Association；
3. 可选一个有产品入口的 Graph Analytics。

### Graphiti

从“Stage 6 默认 Runtime NO-GO”调整为独立 Temporal/Episodic Vertical Slice：

```text
Episode
  ↓
Temporal Fact Graph
  ↓
valid / invalid / as-of
```

`MemoryDeclaration` / Temporal SQL 继续是 Canonical，不建立两套互相争夺权威的 Memory System。

## 新文档

- 架构与面试复盘：`docs/superpowers/specs/2026-09-04-mnemox-v2-graph-evolution-and-portfolio-architecture.md`
- 实施计划：`docs/superpowers/plans/2026-09-04-mnemox-v2-neo4j-graphiti-implementation-plan.md`

## 实施顺序

```text
图领域模型
  ↓
GraphStore 契约
  ↓
Optional Neo4j Backend
  ↓
Knowledge / Learning Path
  ↓
Explainable Multi-hop
  ↓
真实数据 Benchmark
  ↓
Graphiti Temporal Slice
  ↓
可选 Graph Analytics
  ↓
上线 / Architecture Story / 面试材料
```

如果时间不足，Graph Analytics 可以不做；Optional Neo4j Backend、Knowledge Path、Graphiti Temporal Slice 和真实 Benchmark 必须优先做完整。

## 面试复盘原则

以后介绍技术选型，不只回答“用了什么”，还要能回答：

- 原来遇到了什么问题；
- 为什么第一版没有直接用该技术；
- 什么时候现有方案开始不自然；
- 新技术解决了什么；
- Benchmark 和正确性如何；
- 引入了什么新成本；
- 为什么最终采用当前职责分工；
- 出问题如何 fallback / rebuild / rollback。

核心目标是让每个技术都形成：

```text
Problem → Decision → Implementation → Evidence → Trade-off → Evolution
```

而不是只形成技术栈列表。
