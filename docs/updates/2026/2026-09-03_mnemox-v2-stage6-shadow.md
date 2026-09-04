# Mnemox V2 Stage 6：Neo4j / Graphiti Shadow 第一纵向切片

> 日期：2026-09-03
> 状态：历史中间记录；**已由 2026-09-04 Stage 6 最终双 NO-GO 收口取代**
> 最终结论见 `2026-09-04_mnemox-v2-stage6-final.md` 与 `2026-09-04-mnemox-v2-stage6-final-go-no-go.md`。

## 本轮范围

Stage 5 Sparse/Reranker 工程门禁收口后，按明确授权进入 Stage 6。Stage 6 坚持：

```text
SQLite / PostgreSQL = 规范来源
SqlGraphStore        = 产品图查询
Neo4j / Graphiti     = 默认关闭、可删除、可重建 Shadow
```

任何 Shadow 失败都不能改变用户结果，也不能成为产品写入的事实来源。

## Neo4j 第一纵向切片

新增/完成：

- `neo4j>=6.3,<7` 仅进入 `requirements-spike.txt`；
- `docker-compose.yml` 增加 `graph-shadow` profile，默认 `docker compose` 仍只有 db/backend/frontend；
- Neo4j host 端口只监听 `127.0.0.1`；
- `Neo4jGraphStore`；
- 唯一约束、user/sql 索引；
- 固定参数化 Cypher；
- 按用户完整 rebuild；
- source delete；
- health；
- Claim→Concept→Claim；
- ClaimRelation 1～3 hop；
- Concept structure；
- `neo4j_graph` KnowledgeProjectionOutbox target；
- worker target 隔离和现有 retry/DLQ 状态；
- Association V2 脱敏 Shadow diff。

Neo4j 投影刻意不保存：

```text
Claim statement
Unit text
Evidence excerpt
资料正文
资料标题
用户原始 query
```

只投影稳定 ID、user scope、类型、confidence、review/lifecycle 查询所需字段和关系。

## Shadow 发现的语义问题

本轮不是“照着 SQL 翻译 Cypher”就结束，实际发现两个容易造成静默错误的边界：

1. `EXEMPLIFIES` 同时可能存在于 Claim→Concept 与 Claim→Claim。Neo4j variable path 如果不限制节点类型，会穿过 Concept，产生 SQL 不存在的 direct path。
2. `SqlGraphStore` direct traversal 与 unified candidate limit 耦合。shared 候选接近上限时，direct 后续 hop 会提前停止。Neo4j 必须复刻同一 budget 语义才能做公平 Shadow diff。

修正后，1000 / 5000 Claim 合成图均达到：

```text
ID set match          = 100%
path signature match  = 100%
score signature match = 100%
cross-user hits       = 0
raw property leak     = 0
```

## Neo4j 真实临时环境

使用：

```text
neo4j Python driver = 6.3.0
server image        = neo4j:5.26-community
```

真实临时容器专项：

```text
2 passed
```

覆盖 rebuild、query、隔离、source delete、health、raw-property guard，以及错误凭据时 Shadow unavailable 但 canonical SQL 会话仍可继续使用。

同一临时实例在 5000 Claim benchmark 后的单次资源快照约为：

```text
Neo4j process memory ≈ 714 MiB
/data                 ≈ 524 MiB
```

这不是生产容量预测，但足以说明额外图服务存在不可忽略的常驻资源和备份成本，最终 Go/No-Go 必须把它与查询收益一起计算。

## Neo4j 规模评测

入口：

```bash
cd backend
PYTHONPATH=. venv/bin/python evaluate_graph_shadow.py \
  --neo4j-uri <disposable-bolt-uri> \
  --neo4j-user neo4j \
  --neo4j-password <password> \
  --sizes 1000,5000 \
  --queries 30
```

### 1000 Claim

| Probe | SQL p95 | Neo4j p95 | SQL/Neo4j |
| --- | ---: | ---: | ---: |
| direct | 16.92 ms | 19.39 ms | 0.87x |
| shared | 12.08 ms | 8.91 ms | 1.36x |
| combined | 29.20 ms | 25.01 ms | 1.17x |

rebuild 约 `1.29 s`。

### 5000 Claim / 约 10k 图边

| Probe | SQL p95 | Neo4j p95 | SQL/Neo4j |
| --- | ---: | ---: | ---: |
| direct | 23.71 ms | 25.77 ms | 0.92x |
| shared | 23.09 ms | 16.74 ms | 1.38x |
| combined | 33.97 ms | 19.20 ms | **1.77x** |

rebuild 约 `2.47 s`。

因此当前不能简单判定 Neo4j Go 或最终 No-Go：较大 combined 图查询开始出现性能收益，但 direct-only 无优势，而且真实匿名图、资源、投影 lag、备份/恢复/凭据/监控还没验收。

当前决策：

```text
NEO4J_GRAPH_SHADOW → 可以继续
NEO4J_GRAPH_ENABLED → 必须保持 false
Stage 7 Neo4j 灰度 → 不得开始
```

详见：

`docs/superpowers/specs/2026-09-03-mnemox-v2-stage6-neo4j-shadow-hold.md`

## Graphiti 第一纵向切片

确认当前 spike 版本：

```text
graphiti-core = 0.30.1
```

没有沿用旧版 `delete_group()` API。当前实现适配 0.30：

- `Neo4jDriver(..., database=...)`；
- `Graphiti(graph_driver=..., store_raw_episode_content=False)`；
- telemetry 初始化前强制 `GRAPHITI_TELEMETRY_ENABLED=false`；
- group 生命周期通过 driver 参数化 Cypher 删除；
- Graphiti 仍为独立可选 spike 依赖，不进入默认 requirements。

`GraphitiShadowAdapter` 当前只允许：

### Claim episode

```text
当前用户
+ confirmed Claim
+ active lifecycle
+ current Revision
+ active Source
+ 有 Evidence
```

### Temporal episode

只读取已经进入规范审计历史的：

```text
confirmed
superseded
expired
```

不会摄入：

```text
staged conflict
ignored/inaccurate
其他用户状态
原始 conversation transcript
```

这使 Graphiti 的候选价值聚焦在“事实什么时候生效、什么时候被替代”，而不是再复制一个静态 Claim 图。

当前只用 fake-client / 合成状态做边界测试；**没有把用户真实记忆发送给外部 LLM，也没有为本轮验证产生 Graphiti 模型调用成本。**

Graphiti 还没有完成：

- 真实 synthetic episode 的 LLM/embedding ingestion；
- temporal search / fact invalidation 对照；
- 路径/时态结果 diff；
- provider 模型、token、成本和延迟评测；
- source lifecycle 与 conflict correction 的真实 Graphiti 删除/重建验收；
- Go/No-Go。

## 回归

Stage 6 契约：

```text
8 passed
```

真实 Neo4j 专项：

```text
2 passed
```

知识层 Stage 0～6 组合回归：

```text
70 passed, 2 skipped
```

两个 skipped 是需要显式外部 PostgreSQL / Neo4j 环境变量的可选集成门禁；真实 Neo4j 专项已另外显式运行并通过。

56-case Association compare 继续保持：

```text
V2 explicit Recall@5 = 1.0
V2 implicit Recall@5 = 1.0
cross-user = 0
deleted residual = 0
unsupported display = 0
negative false positive = 0
```

## 当前结论

Stage 6 已经真正进入，但远未完成。

```text
Neo4j:
  正确性/隔离/重建/删除/Shadow diff ✅
  目标规模性能 🔶 mixed，5000 combined 有价值信号
  真实图/资源/生产运维 ⏳
  Stage 7 切流 ❌ 禁止

Graphiti:
  0.30 API/telemetry/输入边界 ✅
  时态审计历史过滤 ✅
  真实模型 ingestion/search/cost ⏳
  Go/No-Go ⏳
```
