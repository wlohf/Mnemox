# Mnemox V2 Stage 6：Neo4j Shadow Hold 决策

> 日期：2026-09-03
> 状态：**已被 2026-09-04 最终 Stage 6 ADR 取代**
> 历史决策：Hold / 暂不进入 Stage 7
> 最终结论：Neo4j NO-GO；请以 `2026-09-04-mnemox-v2-stage6-final-go-no-go.md` 为准。

## 1. 问题

Neo4j 的 Stage 6 目标不是证明“图数据库能跑”，而是回答：

> 在 Mnemox 当前 Claim 图和固定查询形态下，额外引入 Neo4j 是否比 `SqlGraphStore` 有足够明确的质量、性能和维护净收益？

实施设计第 10.5 节要求路径正确性、用户隔离、删除、重建、故障回退、目标规模收益和生产运维门禁全部满足，才能进入 Stage 7。

## 2. 已完成的 Shadow 能力

- `neo4j>=6.3,<7` 只在 `requirements-spike.txt`；
- `docker-compose.yml` 使用 `graph-shadow` profile，默认部署不启动 Neo4j；
- host 端口只绑定 `127.0.0.1`；
- `Neo4jGraphStore` 使用固定、参数化 Cypher，不提供 Text2Cypher；
- 节点/关系带 user scope，查询显式过滤 `user_id`；
- Neo4j 投影不保存 Claim statement、Unit text、Evidence excerpt、资料正文或标题；
- SQL 是唯一规范来源，可以按用户 rebuild/delete；
- `neo4j_graph` 进入 KnowledgeProjectionOutbox，当前只接受 `rebuild_user`；
- worker 按 projection target 隔离，Neo4j Shadow 不会消费 Chroma backlog；
- Association V2 仍只使用 `SqlGraphStore` 形成用户结果；Neo4j 只计算脱敏 diff；
- Shadow diff 不记录用户 query、Claim 原文或原始 ID 列表。

## 3. Spike 中发现并修正的语义问题

Shadow 对照先后暴露两个重要问题：

1. `EXEMPLIFIES` 既可能是 Claim→Concept，也可能是 Claim→Claim。Neo4j variable path 如果不限制节点类型，会错误穿过 Concept。
2. `SqlGraphStore` 的 direct traversal 与 unified candidate `limit` 耦合：shared 已接近候选上限时，direct 后续 hop 会提前停止。Neo4j 若独立跑满 depth 再合并，结果会与产品基线不同。

最终 Neo4j 查询按 SQL 候选预算语义执行后，合成图达到：

```text
ID set match             = 100%
path signature match     = 100%
score signature match    = 100%
cross-user hits          = 0
raw knowledge properties = 0
```

这些问题说明 Shadow 的价值之一就是发现“看似等价、实际不等价”的图语义，而不是单纯比较语法。

## 4. 可复现 benchmark

评测入口：

```bash
cd backend
PYTHONPATH=. venv/bin/python evaluate_graph_shadow.py \
  --neo4j-uri <disposable-bolt-uri> \
  --neo4j-user neo4j \
  --neo4j-password <password> \
  --sizes 1000,5000 \
  --queries 30
```

5000 Claim 图约包含：

```text
5,000 Claim
5,000 ClaimConceptLink
4,999 ClaimRelation
100 Concept
```

即约 10k 图关系。所有查询为固定 1～3 hop，不调用外部模型。

### 1000 Claim / 30 anchors

| Probe | SQL p95 | Neo4j p95 | SQL/Neo4j |
| --- | ---: | ---: | ---: |
| direct | 16.92 ms | 19.39 ms | 0.87x |
| shared | 12.08 ms | 8.91 ms | 1.36x |
| combined | 29.20 ms | 25.01 ms | 1.17x |

rebuild 约 `1.29 s`。

### 5000 Claim / 30 anchors

| Probe | SQL p95 | Neo4j p95 | SQL/Neo4j |
| --- | ---: | ---: | ---: |
| direct | 23.71 ms | 25.77 ms | 0.92x |
| shared | 23.09 ms | 16.74 ms | 1.38x |
| combined | 33.97 ms | 19.20 ms | **1.77x** |

rebuild 约 `2.47 s`。

## 5. 当前解释

证据不是单向的：

- direct-only 路径没有证明 Neo4j 优势；
- shared/combined 随图规模增长开始出现收益；
- 5000 Claim combined 已超过“值得继续评估”的性能改善幅度；
- 但这仍是本机合成图，不代表真实用户图；
- Neo4j 还引入独立服务、projection lag、备份/恢复、凭据、监控、桌面双实现等成本。

因此当前不能合理得出两个极端结论：

```text
“Neo4j 一定值得上”  ❌
“Neo4j 已经没有价值” ❌
```

更合适的判断是继续 Shadow，但禁止产品切流。

## 6. 当前 Go / No-Go 检查

| 门槛 | 当前状态 |
| --- | --- |
| 路径正确性 | ✅ 合成固定路径 100% 对齐 |
| 跨用户泄漏 | ✅ 0 |
| source delete / rebuild | ✅ 专项与真实临时 Neo4j 通过 |
| Neo4j 故障不影响产品 SQL | ✅ Shadow 独立，错误凭据时 health unavailable，canonical SQL 仍可继续查询 |
| 目标规模明确净收益 | 🔶 mixed；5000 combined 有收益，direct 无收益 |
| 投影 lag / DLQ / 认证失败 | 🔶 DLQ/失败状态已有；lag/真实认证专项待补 |
| 真实匿名图 | ⏳ 未验收 |
| 生产备份/恢复/凭据/资源/监控 | 🔶 临时实例已记录约 714 MiB 内存、524 MiB `/data`；正式容量、备份恢复、凭据轮换和监控仍未验收 |
| 桌面无需 Neo4j | ✅ 默认 profile 关闭，SqlGraphStore 保留 |

## 7. 决策

```text
NEO4J_GRAPH_SHADOW = 可继续受控评测
NEO4J_GRAPH_ENABLED = 必须保持 false
Stage 7 Neo4j 灰度 = 禁止开始
```

只有剩余门禁完成后才输出最终 Go / No-Go ADR。

如果真实图、资源和运维证据不能证明净收益，则最终 No-Go；如果 combined/多跳场景在真实规模稳定获得明显收益，且运维成本可接受，再讨论小范围服务端灰度。

本结论不影响 Graphiti。Graphiti 的候选价值是时态事实与关系演化，必须独立评估。
