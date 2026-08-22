# 2026-08-22 检索生命周期、质量门禁与 Qdrant Spike 决策

## 状态

有效。上游依赖为 [学习智能底座架构决策](2026-08-03-learning-intelligence-foundation-architecture.md) 和 [RetrievalRouter 资料主链收口](2026-08-22-retrieval-router-material-closure.md)。本决策不启动 Phase 2，也不引入新的生产向量库依赖。

## 背景

PR #8 已将资料、笔记、已确认记忆、概念与学习者状态收敛到统一 `RetrievalRouter`。但资料上传、项目关联和重建仍分别直接写入 Chroma；索引失败不持久化，删除失败会被吞掉，旧 chunk 与模型变更缺少统一版本语义，也没有可重复运行的离线质量集。

GitHub Actions [CI run 32559668354](https://github.com/wlohf/Mnemox/actions/runs/32559668354) 已确认 PR #8 的 Backend、Frontend、PostgreSQL 16、Chromium、Windows smoke 和 Repository integrity 六项均通过。真实 Electron 启动、安装升级和正式生产库升级仍不等于已完成。

## 决策一：规范来源与投影契约

规范事实仍为 `materials.content`、资料元信息和原始上传文件。新增两张**可删除、可重建的 SQL 派生表**：

1. `retrieval_projections`：按 `(user_id, source_type, source_id, backend)` 唯一记录状态、操作、来源版本、已索引版本、内容摘要、配置指纹、embedding 模型、分块参数、SQL / 向量片段数量、尝试次数和最近错误。
2. `retrieval_projection_chunks`：按 `(projection_id, chunk_index)` 唯一保存可重建的 SQL chunk 清单、来源版本、文本和摘要，为关键词 / BM25 路径提供稳定输入。

状态集合为 `pending → indexing → ready / degraded / failed` 和 `deleting → deleted / failed`。投影仅对用户建立 `ON DELETE CASCADE` 外键；`source_id` 不对资料建立外键，以便规范资料被删除后仍可保留失败清理墓碑并跨重启重试。

Alembic head 为 `20260822_10`；SQLite lightweight migration 与 PostgreSQL Alembic 使用相同表、约束和索引。

## 决策二：统一生命周期

`RetrievalProjectionService` 是资料索引变更的唯一新写入边界：

- `ingest`：先提交规范资料，再生成 SQL chunk 清单，最后写入 Chroma；无 embedding 或关闭同步时保留可检索 SQL 清单并标记 `degraded`。
- `refresh`：内容、标题或项目范围变化时更新来源签名、递增版本并替换旧 SQL / 向量 chunk。
- `forget`：先在资料删除事务中写入 `deleting` 墓碑并移除 SQL 清单，再物理删除当前用户向量；失败保留 `failed + operation=forget`，用户和启动恢复均可重试。
- `rebuild`：从当前用户的规范 SQL 资料重建，绝不清空其他用户的向量。
- `retry`：根据墓碑操作恢复失败索引或失败删除。
- 配置失效：embedding 模型、base URL、chunk size 或 overlap 改变时标记旧投影为 `degraded` 并要求重建。

主聊天、Agent 和资料搜索继续只依赖 `RetrievalRouter`；关键词 backend 优先使用用户隔离、版本匹配的 SQL 清单，并在历史资料尚未建立清单时从规范内容回退。

## 决策三：质量门禁

评测入口为 `backend/evaluate_retrieval.py`；固定数据集是 `backend/tests/fixtures/retrieval_eval_cases.json`，包含 13 份双用户资料、3 条笔记、5 个概念、15 个有效双语问题与 1 个空查询兼容用例。

评测记录 Recall@5、Recall@10、MRR、NDCG@10、资料命中率、平均延迟、P95、跨用户泄漏、空查询与删除残留。使用确定性的本地 64 维 token-hash embedding，不调用外部 API，因此结果可以稳定复现，但**不能替代真实 embedding、真实用户问题或大规模容量测试**。

CI 执行：

```bash
cd backend
python evaluate_retrieval.py --backend hybrid --min-recall-at-5 0.75 --summary-only
```

候选 Spike 执行：

```bash
cd backend
python -m pip install -r requirements-spike.txt
python evaluate_retrieval.py --backend all --include-qdrant --summary-only
python -m pytest -q tests/test_qdrant_retrieval_spike.py
```

## 决策四：Qdrant 结论为暂不切换

Qdrant Local 使用真实 `qdrant-client`、命名 dense / sparse 向量、IDF 稀疏权重、Qdrant 原生 RRF、按 `user_id` / `material_id` 过滤，以及可选**轻量词项重排**。该重排不是神经 cross-encoder，不能描述为生产级语义 reranker。

2026-08-22 同一固定评测集的一次本地结果：

| 后端 | Recall@5 | MRR | NDCG@10 | 平均延迟 | P95 | 跨用户泄漏 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| SQL keyword / BM25 | 0.9833 | 1.0000 | 0.9158 | 5.356 ms | 13.691 ms | 0 |
| Chroma dense | 0.8500 | 0.8800 | 0.7782 | 4.279 ms | 8.187 ms | 0 |
| Chroma + keyword + RRF | 0.9833 | 0.9667 | 0.8782 | 6.812 ms | 9.116 ms | 0 |
| Chroma 关闭 embedding 后关键词降级 | 0.9833 | 1.0000 | 0.9158 | 3.873 ms | 6.526 ms | 0 |
| Qdrant dense + sparse + RRF | 0.9500 | 0.9667 | 0.8912 | 4.552 ms | 12.789 ms | 0 |
| Qdrant + 轻量词项重排 | 0.9833 | 0.9667 | 0.8932 | 4.075 ms | 9.383 ms | 0 |
| Qdrant 无 embedding 的 sparse 降级 | 0.9833 | 1.0000 | 0.9158 | 2.678 ms | 5.039 ms | 0 |

延迟是同一环境的一次进程内测量，不构成稳定性能承诺。该小型词项友好语料中 SQL keyword 自身已很强，Qdrant 原生融合的 Recall@5 甚至低于当前混合基线；加轻量重排后只追平 Recall@5，NDCG 增益不足以证明值得承担新增 Windows / Docker 打包、迁移、维护和运维成本。真实 embedding、Windows 分发、资源占用和大语料并未完成验收。

**结论：保留 Chroma + SQL keyword + RRF 为生产实现；Qdrant 只保留可复现的可选离线 Spike，不加入 `backend/requirements.txt`。**未来只有真实语料质量或维护收益显著超过现有基线，并补齐 Windows、删除重建、降级、资源与成本门槛后，才重新开启采纳决策。

## 下一功能模块

继续 Phase 1 的**概念图谱自动抽取、人工确认 / 合并 / 删除、证据回填和先修缺口闭环**；不提前引入 LangGraph、多 Agent、语音或 MCP。
