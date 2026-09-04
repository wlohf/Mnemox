# Mnemox V2 Stage 0：契约、评测与关闭开关

## 本周期目标

- 在不改变生产检索、数据库 schema 或用户数据的前提下，固定 Claim 中心知识图谱的黄金语料、Association V1 基线、feature flag 和预算边界。
- 完成 Stage 0 退出门禁后停止，不进入 Stage 1。

## 指标与范围

- 对应产品目标：未来把联想从显式概念共现升级为可核对双侧观点与原文证据的跨来源关联。
- Baseline / 目标 / 时间窗：2026-09-02 记录 Association V1 显式/隐式 Recall@5、MRR、来源 Recall@5、无结果率、延迟、用户隔离和删除残留；Stage 0 不设 V2 提升结论。
- 本周期范围：合成评测语料、离线 V1 runner、关闭的配置、契约测试、文档导航与路线图窗口。
- 明确不做：Claim SQL 模型/迁移、抽取 Schema/worker、LLM 调用、Entity Resolution、知识向量投影、GraphStore、Association V2 API/UI、Neo4j 或产品切流。

## 已完成

### 1. 契约与评测

- 新增 56 个合成 Unit，其中 50 个带人工 Claim/Evidence 标注；Evidence quote 均能在当前 Unit 原文中精确匹配。
- 新增 56 个跨来源联想问题，显式/隐式、中英文各 28 个；覆盖规范名、Alias/同义词、隐含概念、反例、双向跨用户哨兵和删除来源。
- 新增 `evaluate_knowledge.py`，使用临时 SQLite 直接调用现有 `association_service.find_associations`，不初始化 Provider、不访问网络。
- runner 同时记录 Concept 和关联来源 Recall@5/MRR、无结果率、均值/P95 延迟，并输出 fixture 与确定性结果 SHA-256。
- 生命周期探针先删除规范 Note 及其 ConceptLink，再验证 V1 不返回残留；所有结果按 fixture owner 检查跨用户命中。

### 2. Feature Flag 与安全上限

- 新增并默认关闭：`KNOWLEDGE_V2_ENABLED`、`KNOWLEDGE_LLM_EXTRACTION_ENABLED`、`ASSOCIATION_V2_ENABLED`、`ASSOCIATION_V2_SHADOW`、`KNOWLEDGE_SEMANTIC_AUTO_RESOLVE_ENABLED`、`NEO4J_GRAPH_ENABLED`、`NEO4J_GRAPH_SHADOW`、`GRAPHITI_ENABLED`、`GRAPHITI_SHADOW`。
- 固定初始上限：Unit `8,000` 字符、每 Unit `12` 个 Claim、Claim `500` 字符、结构化输出 `12,000` 字符、每次调用 `30s`。
- 固定初始预算：每 Run `64` 次模型调用、`64,000` 估算 Token；每用户每日 `256,000` 估算 Token。
- Stage 0 只声明和测试这些配置；没有代码读取开关来改变生产行为，也没有模型预算扣减逻辑。

### 3. 路线图与兼容边界

- 文档导航将 V2 实施设计登记为当前有效、分阶段受控的设计。
- 路线图允许 Stage 0 在当前 Phase 2 收口期间作为零产品行为门禁完成；Stage 1 必须等待 Stage 0 和当前 Phase 2 发布/数据库收口，并以独立变更启动。
- Stage 1～7 保持严格顺序；首版固定 `SqlGraphStore`，Neo4j/Graphiti 只能在 Stage 6 分别进行 Shadow Spike，Stage 7 依赖各自新的 go ADR。
- 当前 Association V1、Concept Graph、Temporal Memory、Material Retrieval、数据库 head、API、前端和部署依赖均未改变。

## 涉及文件

- `backend/evaluate_knowledge.py`
- `backend/tests/fixtures/knowledge_extraction_eval_cases.json`
- `backend/tests/fixtures/association_v2_eval_cases.json`
- `backend/tests/test_knowledge_stage0.py`
- `backend/app/config.py`
- `backend/env.example`
- `.env.example`
- `backend/README.md`
- `docs/README.md`
- `docs/technical.md`
- `docs/roadmap.md`
- `docs/progress.md`
- `docs/superpowers/specs/2026-09-02-mnemox-v2-claim-centered-knowledge-graph-implementation.md`

## 失败、降级与数据变更

- 失败模式与降级：本阶段没有运行时路径；baseline 失败只阻止后续 Stage 1，不影响产品。现有 Association V1 始终是唯一产品实现。
- 迁移 / 回填 / 兼容策略：没有数据库迁移或数据回填；所有新开关关闭时行为与此前一致。
- 权限、隐私和数据保留影响：fixture 明确标记为合成数据，不含真实用户数据；跨用户哨兵是人工生成的稳定字符串。runner 使用一次性临时数据库并在退出时删除。

## 验证结果

- `cd backend && venv/bin/python -m pytest -q tests/test_knowledge_stage0.py`：`5 passed`。
- `cd backend && venv/bin/python evaluate_knowledge.py --summary-only`：显式 Recall@5/MRR/来源 Recall@5/MRR `1.0000`；隐式对应指标 `0.0000`，无结果率 `1.0000`；隔离违规 `0`；删除残留 `0`；外部模型调用 `0`。
- `cd backend && venv/bin/python -m pytest -q`：`502 passed, 10 skipped, 58 subtests passed`。
- `cd frontend && npm run test -- --run`：`26 files / 91 tests passed`。
- `cd frontend && npm run lint`：通过；`npm run build`：通过。
- `git diff --check`：通过；仅报告既有 PowerShell 文件未来 LF/CRLF 转换提示，无 whitespace error。

## 验收证据与发布

- 单元 / 集成 / Eval 证据：fixture 完整性、Evidence grounding、指标算法、默认关闭/上限配置、两次 baseline 结果摘要一致、用户隔离与删除探针均由 `test_knowledge_stage0.py` 覆盖。
- 日志、指标或截图链接：离线 runner 输出 JSON；无生产日志、截图或外部服务。
- Feature Flag / 灰度范围：九个开关全部默认 `false`；无灰度用户。
- 回滚方式：移除 Stage 0 fixture/runner/文档声明和未接线配置即可；无 schema downgrade、投影清理或用户数据恢复。

## 已知限制 / 后续事项

- 语料是人工合成回归集，不代表真实用户分布，也不能证明 V2 产品质量。
- V1 显式样本表现满分，主要反映固定词表和 Alias 能力；隐式 Recall 为 0 是预期缺口，不应通过放宽字符串匹配伪装修复。
- 延迟是单进程临时 SQLite 实测，只用于同一 runner 的趋势记录，不是生产容量承诺。
- 本记录完成后，产品负责人于同日明确授权 Stage 1 的默认关闭 schema 切片；结果见 [Stage 1 更新记录](2026-09-02_mnemox-v2-stage1.md)。该授权不包含 Stage 2 自动抽取或 Neo4j/Graphiti runtime。
