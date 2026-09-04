# Mnemox V2 Stage 2：统一抽取、Grounding 与可恢复 Run

## 本周期目标

- 让确定性规则与 LLM 抽取共享同一套严格 Pydantic Schema、Grounding、去重和审核边界。
- 把抽取从同步副作用改为可租约、可重试、可取消、可恢复且支持 Unit 级 partial 的持久任务。
- 保持所有自动 Claim 为 `pending`；没有可定位 Evidence 的候选绝不写入。
- 本阶段不实现 Entity Resolution、ClaimRelation 持久化、Association V2、知识向量投影或外部图运行时。

## 已完成

### 1. 统一 Extraction Schema 与 Grounding

- 新增 `KnowledgeExtractionResult` 及 Evidence、ConceptMention、Claim、ClaimRelation 的严格模型；未知字段、越界长度/置信度、重复本地 ID、悬空关系和自环都会被拒绝。
- `DeterministicKnowledgeExtractor` 将定义、别名、因果、先修与建议等保守规则包装到共享 Schema，不初始化 Provider、不访问网络。
- `LLMKnowledgeExtractor` 优先使用 Provider 可选的 strict structured output；不支持时回退到 JSON 文本并再次通过同一 Pydantic 模型验证，普通 chat 契约保持不变。
- Grounding 先做原文精确匹配，再做 NFKC、空白和标点归一匹配，并把命中映射回原始字符范围；无 Evidence 或无法定位的候选直接丢弃。
- Claim 指纹在来源版本内幂等；重叠 chunk 的 Evidence 按绝对来源字符范围合并，正文中真正重复但位置不同的证据继续保留。

### 2. Durable Extraction Run

- 新增 `knowledge_extraction_runs` 和迁移 `20260903_20`，持久化 extractor/schema/provider/model/input 身份、状态、尝试次数、可用时间、租约、错误摘要、usage 和统计。
- 同一 source revision、extractor、版本、schema 与输入哈希只创建一个 run；强制重试也复用身份，不重复 Claim/Evidence。
- worker 先以短事务取得租约，再执行抽取；PostgreSQL 使用 `FOR UPDATE SKIP LOCKED` 协调多实例，SQLite 明确只启动单个应用内消费者。
- 过期租约可回收，失败使用有界退避；用户可以查询、重试或取消自己的 run。每个 Unit 使用 savepoint 隔离，单 Unit 失败得到 `partial`，已成功写入不回滚，重试只补失败 Unit。
- 模型调用次数、估算 Token、输出长度、单次超时、run 总量和用户 UTC 日预算均在调用边界执行；持久错误只保留脱敏摘要，不保存完整 prompt。

### 3. 产品接线与最小状态 UI

- `KNOWLEDGE_V2_ENABLED=true` 时，Material/Note 来源登记会幂等创建确定性 run；只有同时打开 `KNOWLEDGE_LLM_EXTRACTION_ENABLED` 才创建 LLM run。
- 原 Material 规则概念同步路径和章节 LLM 抽取入口在 V2 模式下改为创建 durable run，不再直接用模型结果修改 Concept。
- 新增资料抽取摘要、run 查询、创建、重试和取消 API；所有入口校验当前用户和 current revision。
- 资料列表只展示抽取状态与待审核 Claim 数量，没有引入图谱页面或复杂审核 UI。
- 自动 Claim 始终写入 `pending`；确定性抽取标记为 `explicit`，LLM 抽取标记为 `inferred`。缺少 AI Key 只使 LLM run 失败，确定性 run 与资料保存仍成功。

## 验证结果

- Stage 2 专项：`13 passed`，覆盖严格 schema、确定性无网络、structured-output/JSON fallback、精确/归一 Grounding、无定位零写入、重叠去重、幂等重试、partial 恢复、租约回收、取消、跨用户、状态摘要和缺少 AI Key 降级。
- Stage 0～2、迁移和事务所有权组合专项：`47 passed`；关键兼容路径：`30 passed`。
- 完整后端回归：`534 passed, 14 skipped, 58 subtests passed`。
- 前端：`26 test files / 91 tests passed`，生产 build 通过。
- 全新一次性 PostgreSQL 16 从冻结基线升级到 head `20260903_20`；`alembic check` 无 drift；`9 passed` 候选门禁覆盖真实 `SKIP LOCKED` 双会话竞争和 grounded pending Claim/Evidence 持久化。临时容器和纯测试数据已删除。

## 失败、降级与回滚

- 默认总开关和 LLM 抽取开关仍为 `false`，升级不会回填历史来源，也不会改变 Association V1。
- 关闭 `KNOWLEDGE_LLM_EXTRACTION_ENABLED` 可只保留本地确定性候选；关闭 `KNOWLEDGE_V2_ENABLED` 会停止产品 source hook 与 worker，保留 SQL 数据供恢复或审计。
- 来源 supersede/delete 会取消旧版本未完成 run 并清除租约；run 失败不回滚 Material/Note 领域写入。
- 生产回滚保留新表，不执行破坏性 downgrade；正式 PostgreSQL 仍依赖发布窗口快照和应用版本同步回退。

## 尚未实现

- Stage 3 的 ClaimConceptLink、Entity Resolution、知识专用 embedding collection、候选审核与重建/删除投影。
- ClaimRelation 的 SQL 持久化和 `SqlGraphStore`；Schema 可验证关系候选，但 Stage 2 不保存它们。
- Association V2、Sparse/Reranker、Neo4j/Graphiti consumer、Shadow diff 或图运行时。
- 历史 PostgreSQL dump 恢复到新 head、远程候选 CI 和正式生产升级；这些继续属于发布轨道。

下一开发阶段是 Stage 3，不是直接切换 Association V2 或图数据库。
