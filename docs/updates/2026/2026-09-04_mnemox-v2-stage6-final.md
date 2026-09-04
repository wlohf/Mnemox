# 2026-09-04 Mnemox V2 Stage 6 最终收口与双 NO-GO

## 结论

Stage 6 已完成。

- Neo4j：**NO-GO**。
- Graphiti：**NO-GO**。
- `SqlGraphStore` 继续是唯一产品 GraphStore。
- `UserMemory + MemoryDeclaration` Temporal SQL 继续是事实身份、冲突审核和有效期权威。
- Stage 7 对当前两个候选不进入。

最终决策见 `docs/superpowers/specs/2026-09-04-mnemox-v2-stage6-final-go-no-go.md`。

## 本次完成内容

### Graphiti temporal search

补齐 `GraphitiShadowAdapter.search_temporal`：

- 强制用户 group scope；
- 支持 as-of 查询；
- 按 `valid_at / invalid_at / expired_at` 过滤；
- 只从 deterministic episode UUID 映射回 canonical `MemoryDeclaration.id`；
- 不把 raw fact/query 放进 Shadow diagnostics。

`graphiti_group_id` 从旧的冒号形式改为 `mnemox_user_<id>`。真实 `graphiti-core 0.30.1` 验证证明冒号 group id 会在 `search()` 阶段被 SDK 拒绝。

### Graphiti 生命周期/故障门禁

新增验证：

- superseded SourceRevision 的旧 Claim 不进入 rebuild；
- reviewed temporal history 只允许 confirmed/superseded/expired；
- staged conflict 与其他用户状态不摄入；
- current / historical as-of 能区分旧/新 declaration；
- search provider failure 不泄露 query，不污染 SQL transaction。

### Neo4j lag / DLQ

新增：

- `neo4j_projection_lag_summary`：pending age、processed lag、status count、DLQ count；
- 第二次失败真实进入 DLQ；
- diagnostics 不暴露 payload；
- 产品 factory No-Go 守卫：即使候选 enabled flag 被误打开，`create_graph_store()` 仍返回 `SqlGraphStore`。

## 真实 Graphiti 0.30.1 集成

使用真实 Neo4j 5.26 Community + graphiti-core 0.30.1。

为了把图搜索能力和模型成本分开，集成测试使用官方 `LLMClient / EmbedderClient / CrossEncoderClient` 的阻断子类：任何外部模型调用都会立即失败。

发现两个真实 SDK 边界：

1. group id 只允许 `[A-Za-z0-9_-]+`；
2. 即使 BM25-only，Graphiti 的 Entity/Edge save 路径仍要求非空 vector property。

测试使用本地固定 1024 维零向量，不调用任何外部 embedding 服务。

真实 BM25-only 集成通过：

- 当前 temporal declaration 正确命中；
- 历史 as-of 正确命中旧 declaration；
- foreign group 不泄漏；
- raw episode storage 关闭；
- external model calls = 0。

## SQL vs Graphiti benchmark

相同 synthetic confirmed memory facts、相同唯一 token query、30 个 query：

| Facts | SQL Recall@5 | Graphiti Recall@5 | SQL p95 | Graphiti p95 |
| ---: | ---: | ---: | ---: | ---: |
| 100 | 1.0 | 1.0 | 8.281 ms | 14.242 ms |
| 1,000 | 1.0 | 1.0 | 9.616 ms | 19.147 ms |

Graphiti seed：

- 100 facts：246.36 ms；
- 1,000 facts：1,411.47 ms。

所有 Graphiti benchmark 外部模型调用为 0。

临时 Neo4j/Graphiti 容器在 1,000 temporal facts 后观察到约：

- memory：约 1 GiB；
- `/data`：约 520 MiB。

## Neo4j 最终评估摘要

此前 30-anchor 稳态对照：

| 规模 | Probe | SQL p95 | Neo4j p95 |
| --- | --- | ---: | ---: |
| 1,000 | direct | 16.918 ms | 19.393 ms |
| 1,000 | shared | 12.084 ms | 8.905 ms |
| 1,000 | combined | 29.195 ms | 25.010 ms |
| 5,000 | direct | 23.706 ms | 25.766 ms |
| 5,000 | shared | 23.087 ms | 16.742 ms |
| 5,000 | combined | 33.969 ms | 19.199 ms |

ID/path/score 一致率均 1.0；cross-user / raw property violation 均 0。

Neo4j 在大图 combined/shared 存在性能信号，但 direct 无稳定收益；同时增加一个常驻数据库、备份/恢复/凭据/监控面，桌面端仍必须长期保留 SQL。因此未达到“明确净收益”强门槛。

## 为什么没有继续调用真实 Graphiti LLM

这是有意的 stop rule，而不是遗留 TODO。

Graphiti 在最低成本的 BM25-only 模式已经：

- 同 Recall 下比 SQL 慢；
- 仍依赖 Neo4j 常驻资源；
- 数据模型仍要求 vector field；
- Mnemox 已经有 canonical Temporal SQL。

此时候选已经在“净收益”强门槛失败。继续拿真实用户数据或付费 Provider 做 `add_episode` 只会增加隐私暴露和模型成本，不能改变“先通过基础净收益门槛”的工程原则，因此停止进一步外部模型评测并最终 NO-GO。

## 验证命令

```bash
cd backend
PYTHONPATH=. venv/bin/python -m pytest -q tests/test_graph_shadow_stage6.py

RUN_GRAPHITI_INTEGRATION=1 \
NEO4J_URI=bolt://127.0.0.1:17687 \
NEO4J_USER=neo4j \
NEO4J_DATABASE=neo4j \
PYTHONPATH=. venv/bin/python -m pytest -q tests/test_graphiti_shadow_integration.py

PYTHONPATH=. venv/bin/python evaluate_graphiti_shadow.py \
  --neo4j-uri bolt://127.0.0.1:17687 \
  --neo4j-user neo4j \
  --neo4j-database neo4j \
  --sizes 100,1000 \
  --queries 30
```

最终本地验收：

```text
Stage 6 contract/unit            13 passed
real Graphiti + real Neo4j       3 passed
Stage 0～6 knowledge regression  75 passed, 4 skipped
56-case Association V2           explicit Recall@5 = 1.0
                                 implicit Recall@5 = 1.0
lifecycle/safety probes          all 0 violations
external model calls in Graphiti benchmark = 0
git diff --check                 passed
```

4 个 skipped 均是未显式提供对应外部专项环境时的可选数据库/integration gate；同一轮已经用临时 Neo4j 容器显式执行并通过 Neo4j + Graphiti 的 3 个真实集成测试。

唯一 warning 来自 `graphiti-core 0.30.1` 内部仍使用 Pydantic class-based config 的弃用提示，不来自 Mnemox 代码。

Stage 6 完成后，临时 Neo4j 容器已删除，默认运行时没有增加 Neo4j/Graphiti 服务。
