# Mnemox V2 Stage 4：Association V2 + SqlGraphStore 受控纵向切片

> 日期：2026-09-03
> 状态：🔶 后端纵向切片已通过合成门禁，Stage 4 尚未正式完成

## 本轮目标

在不引入 Neo4j、Graphiti、Qdrant 或新的运行时依赖的前提下，验证 Claim 中心知识图谱是否能让跨资料联想从“只能识别显式概念”提升到“能利用已审核的 Claim→Concept 锚点发现隐含概念”，同时保持证据、用户隔离、删除生命周期和 V1 回滚边界。

## 已实现

- 新增 Alembic 迁移 `20260903_22` 和 SQL `claim_relations`，支持 `supports`、`contradicts`、`refines`、`exemplifies`、`analogous_to`，保留置信度、审核状态、推导类型、rationale 与 evidence provenance。
- 新增 `GraphStore` protocol 与默认 `SqlGraphStore`；关系查询仍以 SQLite/PostgreSQL 为权威来源，不依赖外部图数据库。
- `SqlGraphStore` 只返回当前用户、active Source、current Revision、confirmed/active Claim 且存在 Evidence 的结果；删除、superseded、跨用户 Claim 均不可进入产品结果。
- 新增 `claim_relation_service`，写入关系前同时校验两端 Claim 的用户归属、active Source、current Revision、active Claim 与 Evidence；服务层保持 flush-only，事务仍由请求或 worker 入口拥有。
- 新增 `association_v2_service`：
  - 通过显式 Concept/Alias 与来源 ClaimConceptLink 构建 Query anchor；
  - 融合 exact、知识 Dense（可用时）、SQL sparse reference、confirmed graph path；
  - 按证据身份与来源去重；有明确 source context 时排除同一 Source 的其他 Claim，避免同源内容挤占跨资料联想结果；
  - 使用版本化确定性 Feature Ranker；
  - 无 Evidence 的候选永不展示；
  - Judge 可选且失败时只保留 confirmed graph path，不影响安全降级。
- 新增 `POST /api/knowledge/associate`；只有 `KNOWLEDGE_V2_ENABLED=true` 且 `ASSOCIATION_V2_ENABLED=true` 时启用，V1 路径保持不变。
- 扩展 `evaluate_knowledge.py --mode v2|compare`，离线评测不调用网络或外部模型。

## 评测隔离修正

首次 Stage 4 评测暴露两个异常：`deleted_source_residual_hits=4`、`negative_false_positive_count=2`。排查后确认不是产品删除过滤遗漏，而是评测器把全部 56 个测试 Query Anchor 预先写成 confirmed Material Claim，导致“另一个测试问题”可以成为当前问题的候选结果。

修正为：每个 Query Anchor 只在自己的 case 生命周期内创建，完成评测后立即 tombstone。这样既保留 Stage 3 已审核 Claim→Concept 锚点的模拟，又避免跨 case 污染，不通过降低阈值或放宽测试掩盖问题。

## 验证结果

专项与生命周期回归（加入关系写入生命周期与同源排除回归后复跑）：

```text
68 passed in 89.97s
38 passed in 58.87s  # Stage 4 + lifecycle/schema/transaction 核心子集复跑
```

覆盖 Association V2、Knowledge Source lifecycle、Extraction、Entity Resolution、Knowledge Projection、Schema Migration、Transaction Ownership 与 Release Preflight。全量 `pytest -q` 在当前 300 秒执行窗口内未完成，因此不把“全量后端通过”作为本轮验收结论；后续 CI/发布候选仍需完成完整测试矩阵。

56-case 合成离线对照：

| 指标 | V1 | V2 |
| --- | ---: | ---: |
| 显式 Recall@5 | 1.0 | 1.0 |
| 隐式 Recall@5 | 0.0 | 1.0 |
| 显式 Source Recall@5 | 1.0 | 1.0 |
| 隐式 Source Recall@5 | 0.0 | 1.0 |
| 跨用户泄漏 | 0 | 0 |
| 删除来源残留 | 0 | 0 |
| 无证据展示 | - | 0 |
| 负例误关联 | - | 0 |
| 外部模型调用 | 0 | 0 |

本轮复跑中 V2 显式 p95 约 `35 ms`、隐式 p95 约 `47 ms`，仍明显高于 V1（约 `13 ms` / `7 ms`）；这不阻塞当前质量验证，但需要在 Stage 5 用真实规模数据评估 Sparse 索引与 reranker 性能。

## 为什么暂不标记 Stage 4 完成

当前已经通过核心合成门禁，但完整 Stage 4 退出条件还包括“人工标注的牵强/不支持关联率不高于 5%”以及真实产品灰度。合成负例为 0 只能证明确定性回归集没有已知误关联，不能替代真人对真实资料联想质量的判断。

因此当前状态保持为 **Stage 4 部分完成 / 后端纵向切片通过**：

1. Association V1 继续保留并可通过 feature flag 一键回滚；
2. Association V2 不设为默认产品主线；
3. 不启动 Neo4j/Graphiti runtime；
4. 下一步先补真实中文/双语资料的人工关联标注与灰度，再决定是否正式关闭 Stage 4。
