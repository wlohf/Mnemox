# Mnemox V2 Stage 5：Sparse 规模化与 Reranker 工程收口

> 日期：2026-09-03
> 状态：🔶 工程门禁已收口；真实匿名语料与真人质量验收仍后置，因此不宣称产品验收完成

## 本轮完成内容

Stage 4 的 Association V2 已证明 Claim → Concept/Relation → Claim 能补足隐含联想，但原 sparse 通道会在每次查询时把当前用户全部可见 Claim 拉回 Python 做词法匹配，复杂度随 Claim 数近似线性增长。

Stage 5 现在完成以下工程链路：

```text
Association V2
    ↓
SparseKnowledgeIndex
    ├─ auto（默认）
    │   ├─ SQLite → FTS5
    │   └─ PostgreSQL → native GIN FTS
    └─ reference（显式回滚）

Canonical Claim write
    ↓
knowledge projection hook
    ├─ claim-level dirty marker（savepoint 隔离）
    └─ KnowledgeProjectionOutbox
         ├─ chroma_knowledge
         └─ sparse_knowledge
```

### Sparse 生命周期

- 中文使用应用统一 bigram，英文使用 token；SQLite/PostgreSQL 结果口径一致。
- PostgreSQL 不依赖 `pg_trgm`，使用 `to_tsvector('simple', search_text)` + GIN。
- 普通 Claim 新增、审核、失效与删除只标记对应 Claim dirty，并通过 sparse outbox 做增量 upsert/delete。
- Query 只做 O(1) dirty/state 检查；少量 dirty Claim 增量修复，超过阈值或首次建索引才整用户 rebuild。
- 可选 sparse 标记运行在 nested transaction/savepoint；投影 DDL/数据库错误不会把 canonical write 事务打成 aborted。
- worker 按 `projection_target` 领取任务。Sparse 开启、Embedding 关闭时只消费 `sparse_knowledge`，不会误消费历史 Chroma backlog。
- `KNOWLEDGE_SPARSE_BACKEND=auto` 为默认策略；显式 `reference` 是一键回滚。
- auto 模式下持久 FTS 查询失败会在 savepoint 内回滚并切到 reference 全扫描，产品仍返回经过 SQL 生命周期/Evidence 二次校验的结果。

### PostgreSQL Planner 修复

5,000 Claim bulk rebuild 后，如果统计信息尚未刷新，PostgreSQL Planner 可能先按 `user_id` 拉取全部 5,000 行，再逐行计算 `to_tsvector`，导致一次查询约 80～100ms。

`EXPLAIN (ANALYZE, BUFFERS)` 验证 GIN 路径本身约 15ms，因此 rebuild 结束后现在执行：

```sql
ANALYZE knowledge_claim_sparse;
```

让 Planner 立即使用 GIN，而不是等待 autovacuum/analyze 后再恢复正常计划。

## Reranker

Association V2 现在有两层排序：

```text
Feature Ranker
    ↓
可选 LLM Semantic Reranker
```

默认：

```text
KNOWLEDGE_RERANKER_MODE=feature
```

可选：

```text
KNOWLEDGE_RERANKER_MODE=llm
```

LLM reranker 复用当前用户已有 AI Provider，不新增 cross-encoder/模型下载依赖。候选 Claim 只作为不可信数据参与相关性打分，不改变事实来源；最终展示仍必须通过 SQL 用户隔离、Source/Revision/Claim lifecycle 与 Evidence 校验。

Diagnostics 记录：

- reranker mode/version；
- provider/model；
- latency；
- provider-reported token usage；
- 已配置价格时的参考成本；
- timeout/exception 时的 fallback 状态。

Provider 缺失、解析失败、异常或超时都回退 Feature Ranker，不阻塞 Association 返回。

## 规模基准

### SQLite FTS5

同一合成数据、同一 tokenizer、4 个中英文查询各重复 3 次；结果 parity 全部为 true。

| 可见 Claim | Reference p95 | SQLite FTS5 p95 | p95 加速 |
| ---: | ---: | ---: | ---: |
| 100 | 10.89 ms | 8.60 ms | 1.27x |
| 1,000 | 94.19 ms | 7.28 ms | 12.94x |
| 5,000 | 423.94 ms | 10.58 ms | 40.07x |

5,000 Claim rebuild 约 `2.59 s`。

### PostgreSQL 16 native FTS

独立临时 PostgreSQL 16 容器，不触碰正在运行的 Mnemox PostgreSQL。

5,000 Claim：

```text
Reference p95     = 407.20 ms
PostgreSQL FTS p95 = 29.03 ms
p95 speedup        = 14.03x
result parity      = true
rebuild            ≈ 3.79 s
```

专项 `EXPLAIN` 中 GIN 查询执行约 15ms；端到端 benchmark 还包含 SQLAlchemy round-trip、dirty/state 检查与 Python lexical parity scoring。

## 质量与回归

Stage 5 相关专项当前：

```text
27 passed
```

知识层扩展回归：

```text
63 passed
```

覆盖：

- SQLite FTS5 中文/英文 parity；
- PostgreSQL 中文/英文 parity；
- 用户隔离；
- source/claim 删除；
- rebuild；
- claim-level incremental dirty；
- optional projection failure 不污染 canonical transaction；
- sparse-only worker 不消费 Chroma backlog；
- auto backend reference fallback；
- semantic reranker 排序；
- provider unavailable fallback；
- reranker timeout fallback；
- reranker model/latency/usage diagnostics。

56-case Association 对照重新运行：

- V1 显式 Recall@5 = `1.0`
- V1 隐式 Recall@5 = `0.0`
- V2 显式 Recall@5 = `1.0`
- V2 隐式 Recall@5 = `1.0`
- 跨用户泄漏 = `0`
- 删除来源残留 = `0`
- 无证据展示 = `0`
- 负例误关联 = `0`

因此 Stage 5 工程改动没有降低 Stage 4 合成 baseline。

## 当前结论

从工程实现看，Stage 5 的核心开发已经收口：

- persistent sparse 不再依赖每次查询全量 canonical stale scan；
- Claim 生命周期具备增量 dirty + outbox；
- SQLite/PostgreSQL 都有明显规模收益；
- 默认 auto 有 reference fallback；
- LLM reranker 已有真实 Provider 接线与成本/延迟诊断，默认关闭且安全降级。

仍不能把 **Stage 5 产品验收**写成完全完成，原因只有数据门禁：当前 benchmark/质量集仍是合成或确定性 fixture，尚未使用真实匿名中文/双语资料做相关性与牵强率验收。这个限制与 Stage 4 真人验收后置保持一致。

因此进入 Stage 6 前的口径应为：

```text
Stage 5 engineering = complete
Stage 5 real-data acceptance = deferred
Neo4j / Graphiti = 仍不得直接进入产品 runtime，只能做 Shadow Spike
```
