# 文档导航

> 更新日期：2026-09-04

本目录只保留当前实现基线、仍有效的架构决策、可复用的验证证据和周期更新。需要判断“现在是什么”和“下一步做什么”时，优先阅读现行基线，不要把历史方案当成待办清单。

## 现行基线

| 文档 | 用途 |
| --- | --- |
| [需求基线](requirements.md) | 产品定位、北极星指标、范围、非目标和验收边界 |
| [路线图](roadmap.md) | 阶段顺序、完成标准、当前检查点和冻结清单的唯一权威来源 |
| [技术基线](technical.md) | 当前代码实现、数据边界、运行约定和技术债 |
| [进度文档](progress.md) | 当前发布版本、主线状态、验证证据和已知限制 |
| [正式发布验收](release-acceptance.md) | 候选门禁、Windows 签名与安装、生产升级、发布和停止条件 |
| [API Contract](api/README.md) | OpenAPI 事实源、前端 Service 边界、领域 API 导航与错误契约 |
| [数据库升级演练报告](database-rehearsal-2026-08-05.md) | SQLite/PostgreSQL 计数、SHA256、恢复验证和回滚预案 |

根目录的 [README](../README.md) 是项目总览，[PRODUCT.md](../PRODUCT.md) 是产品说明；Windows 本地启动请看 [启动指南](../启动指南.md)。

## 当前架构决策

| 日期 | 文档 | 状态 |
| --- | --- | --- |
| 2026-09-04 | [Mnemox V2 图架构演进、技术选型与作品集目标决策](superpowers/specs/2026-09-04-mnemox-v2-graph-evolution-and-portfolio-architecture.md) | **当前权威增量决策**：保留 Stage 6 默认 Runtime 双 NO-GO，但把 Neo4j 重新打开为 Optional Graph Backend 建设目标，把 Graphiti 重新打开为独立 Temporal/Episodic Vertical Slice；要求真实 Graph-native 功能、Benchmark、Fallback 和完整选型依据 |
| 2026-09-04 | [Mnemox V2 图基础设施提前建设策略](superpowers/specs/2026-09-04-mnemox-v2-graph-foundation-strategy.md) | 当前有效的基础原则：SQL Canonical、GraphStore 解耦、Projection/Outbox/Shadow/Rebuild 提前准备；已被同日增量 ADR 扩展为“默认 Runtime 不变 + 可选图后端主动建设” |
| 2026-09-04 | [Mnemox V2 Stage 6 最终 Go / No-Go](superpowers/specs/2026-09-04-mnemox-v2-stage6-final-go-no-go.md) | 历史评测结论仍有效：Neo4j / Graphiti 不作为默认产品 Runtime；该结论不再等于“停止实现”，后续按同日增量 ADR建设可选能力 |
| 2026-09-03 | [Mnemox V2 Stage 6 Neo4j Shadow Hold](superpowers/specs/2026-09-03-mnemox-v2-stage6-neo4j-shadow-hold.md) | 已被 2026-09-04 最终 ADR 取代；保留作为中间 Hold 证据 |
| 2026-09-02 | [Mnemox V2 Claim 中心知识图谱实施设计](superpowers/specs/2026-09-02-mnemox-v2-claim-centered-knowledge-graph-implementation.md) | Stage 0～6 工程/Spike 已执行；Stage 6 双 NO-GO，Stage 4/5 的真人与真实匿名质量验收继续单列后置 |
| 2026-08-23 | [SQL 时态记忆生命周期决策](superpowers/specs/2026-08-23-temporal-memory-lifecycle-adr.md) | 当前有效：事实身份、当前事实唯一性、冲突审核、用户纠错、自动失效、派生清理与 Graphiti 暂缓 |
| 2026-08-22 | [概念图谱与学习推荐决策](superpowers/specs/2026-08-22-concept-graph-learning-recommendations-adr.md) | 当前有效：SQL 概念审核、关系来源、人工治理、先修缺口与可解释学习推荐 |
| 2026-08-22 | [检索生命周期与质量决策](superpowers/specs/2026-08-22-retrieval-lifecycle-quality-adr.md) | 当前有效：资料 SQL/Chroma 投影契约、更新/删除/重建、离线质量门禁与真实 Qdrant Local no-go |
| 2026-08-13 | [笔记、上下文与记忆边界决策](superpowers/specs/2026-08-13-note-context-memory-architecture.md) | 当前有效：笔记三层逻辑存储、三阶段检索、记忆候选和学习证据边界；聊天笔记首条 ContextStore 业务流已完成接口收敛，完整生命周期仍待补 |
| 2026-08-03 | [学习智能底座架构决策](superpowers/specs/2026-08-03-learning-intelligence-foundation-architecture.md) | 当前有效：混合 RAG、概念图谱、时态记忆、学习者模型、投影和受控 Spike |
| 2026-07-26 | [知识层 / 检索底座 / Agent 架构决策](superpowers/specs/2026-07-26-knowledge-layer-context-substrate-agent-architecture.md) | 部分仍有效；关系型核心、FSRS、草案确认、用户隔离和 OpenViking 否决证据继续适用 |
| 2026-07-26 | [OpenViking Spike 结论](superpowers/specs/2026-07-26-openviking-spike-result.md) | 保留的否决证据：不满足 Windows 桌面分发门槛 |

08-03 决策覆盖 07-26 决策中关于 `Concept.mastery`、候选检索选型、Agent 框架排除和记忆边界的部分。新的选型或架构变化必须新增带日期的决策文档，并写清验收、删除、迁移和回滚证据。

## 当前实施计划

- [Neo4j / Graphiti 上线前 2～4 周实施计划](superpowers/plans/2026-09-04-mnemox-v2-neo4j-graphiti-implementation-plan.md)：按“领域模型 → GraphStore → Optional Neo4j Backend → Knowledge Path → Explainable Multi-hop → 真实 Benchmark → Graphiti Temporal Slice → 上线/面试材料”执行。

## 启动与开发

- [启动指南](../启动指南.md)：Windows 一键启动、手动启动、依赖准备和数据库迁移。
- [后端 README](../backend/README.md)：FastAPI、环境变量、迁移入口和后端测试。
- [前端 README](../frontend/README.md)：React/Vite、页面、同步和前端测试。
- [功能更新维护说明](updates/README.md)：周期记录的格式、目录规则和验证要求。

## 持续记录

- [更新记录模板](updates/_template.md)
- [2026-09-04 Mnemox V2 图架构演进与 Stage 7 重新打开](updates/2026/2026-09-04_mnemox-v2-graph-evolution-plan.md)
- [2026-09-04 Mnemox V2 Stage 6 最终收口与双 NO-GO](updates/2026/2026-09-04_mnemox-v2-stage6-final.md)
- [2026-09-03 文档来源唯一性治理](updates/2026/2026-09-03_documentation-source-of-truth.md)
- [2026-09-03 Mnemox V2 Stage 6 Neo4j / Graphiti Shadow 第一纵向切片](updates/2026/2026-09-03_mnemox-v2-stage6-shadow.md)
- [2026-09-03 Mnemox V2 Stage 5 Sparse Knowledge 第一纵向切片](updates/2026/2026-09-03_mnemox-v2-stage5-sparse.md)
- [2026-09-03 Mnemox V2 Stage 4 Association V2 + SqlGraphStore 受控纵向切片](updates/2026/2026-09-03_mnemox-v2-stage4.md)
- [2026-09-03 Mnemox V2 Stage 3 Entity Resolution 与 Knowledge Embedding](updates/2026/2026-09-03_mnemox-v2-stage3.md)
- [2026-09-03 Mnemox V2 Stage 2 统一抽取、Grounding 与可恢复 Run](updates/2026/2026-09-03_mnemox-v2-stage2.md)
- [2026-09-02 历史诊断数据可回滚清理](updates/2026/2026-09-02_historical-diagnostic-cleanup.md)
- [2026-09-02 检索长操作并发 Fencing](updates/2026/2026-09-02_retrieval-operation-fencing.md)
- [2026-09-02 检索投影原子身份创建](updates/2026/2026-09-02_retrieval-projection-atomic-identity.md)
- [2026-09-02 Mnemox V2 Stage 0 契约、评测与关闭开关](updates/2026/2026-09-02_mnemox-v2-stage0.md)
- [2026-09-02 Mnemox V2 Stage 1 Canonical Claim Schema](updates/2026/2026-09-02_mnemox-v2-stage1.md)
- [2026-09-02 Pydantic 显式字段兼容边界](updates/2026/2026-09-02_pydantic-field-compat.md)
- [2026-09-02 结构化安全诊断](updates/2026/2026-09-02_structured-safe-diagnostics.md)
- [2026-09-02 服务事务所有权架构守卫](updates/2026/2026-09-02_transaction-ownership-guard.md)
- [2026-09-02 用户画像原子 Upsert](updates/2026/2026-09-02_profile-atomic-upsert.md)
- [2026-09-01 安全错误摘要与诊断边界](updates/2026/2026-09-01_safe-error-boundary.md)
- [2026-09-01 UTC 时间契约与核心链路迁移](updates/2026/2026-09-01_utc-time-contract.md)
- [2026-09-01 用户画像投影事务边界](updates/2026/2026-09-01_profile-transaction-boundary.md)
- [2026-09-01 知识巩固周报来源追溯与只读草案](updates/2026/2026-09-01_weekly-knowledge-consolidation.md)
- [2026-09-01 Coach 干预效果 A/A 观察与成熟归因](updates/2026/2026-09-01_coach-intervention-aa-observation.md)
- [2026-09-01 AgentRuntime 时区、免打扰与多实例调度加固](updates/2026/2026-09-01_agent-runtime-scheduler-hardening.md)
- [2026-09-01 AgentKernel 规则 Planner 降级闭环](updates/2026/2026-09-01_kernel-rules-fallback.md)
- [2026-09-01 AgentKernel 供应商用量与配置单价对账](updates/2026/2026-09-01_agent-kernel-usage-reconciliation.md)
- [2026-08-23 SQL 时态记忆冲突、审核、纠错与自动失效](updates/2026/2026-08-23_temporal-memory-lifecycle.md)
- [2026-08-22 概念图谱与可解释学习推荐闭环](updates/2026/2026-08-22_concept-graph-learning-recommendations.md)
- [2026-08-22 统一检索生命周期、质量评测与 Qdrant 选型](updates/2026/2026-08-22_retrieval-lifecycle-quality.md)
- [2026-08-19 分支整合、冲突消解与文档基线校准](updates/2026/2026-08-19_to_2026-08-19.md)
- [2026-08-13 至 2026-08-17 ContextStore、Coach、Vault 与记忆声明收口](updates/2026/2026-08-13_to_2026-08-17.md)
- [2026-08-13 Phase 1 主线整合与分支收口](updates/2026/2026-08-13_to_2026-08-13.md)
- [2026-08-12 Outbox 运维闭环加固](updates/2026/2026-08-12_to_2026-08-12.md)
- [2026-08-09 Phase 1 工作区整合与验证](updates/2026/2026-08-09_to_2026-08-09.md)
- [2026-08-06 PostgreSQL 常驻 Outbox worker](updates/2026/2026-08-06_to_2026-08-06.md)
- [2026-08-04 至 2026-08-05 学习者模型、事件投影与文档收口](updates/2026/2026-08-04_to_2026-08-05.md)
- [2026-06-01 至 2026-06-07 更新记录](updates/2026/2026-06-01_to_2026-06-07.md)

周期记录用于说明已发生的变更和验证结果，不替代需求、路线图或技术基线。

## 版本与安全

- 当前发布说明：[v1.3.0](../release-notes-v1.3.0.md)。更早版本的发布说明已从工作区清理，历史仍可通过 Git 追溯。
- 不要在文档、脚本或示例中写入真实 API Key。真实密钥只放在本地 `.env` 或设置页的安全存储中。
- 数据库、上传目录、备份和运行产物不属于文档提交内容。

## 清理原则

2026-08-04 至 2026-08-05 已删除被现行基线替代的早期系统设计、Coach/RAG 方案、一次性实施计划、旧 UI 记录、旧修复记录和旧版本发布说明。后续若历史背景仍有证据价值，应合并成短说明或独立 ADR；不要继续创建与当前路线图并行的“第二份真相”。
