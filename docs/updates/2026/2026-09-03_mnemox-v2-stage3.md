# Mnemox V2 Stage 3：Entity Resolution 与 Knowledge Embedding

## 本周期目标

- 把 Stage 2 的概念提及解析为可审核的 Claim→Concept 语义锚点。
- 只允许 canonical/alias exact 和既有人工决定自动确认，禁止纯语义自动合并 Concept。
- 为 Concept、Claim、Material Unit、Note Unit 建立独立、可删除、可重建的知识 embedding 投影。
- 补齐人工审核、失败降级、用户隔离、双数据库迁移和发布轨道的历史 dump 恢复演练。
- 本阶段不实现 ClaimRelation、Association V2、`SqlGraphStore`、Sparse/Reranker 或 Neo4j/Graphiti runtime。

## 已完成

### 1. 解析与审核数据契约

- 新增 Alembic migration `20260903_21` 和 SQLite lightweight migration，创建：
  - `entity_resolution_candidates`：提及、候选 Concept、各阶段分数、决定和决定来源；
  - `claim_concept_links`：已确认的 Claim→Concept 关系和推导来源；
  - `knowledge_embedding_projections`：四类对象的内容/配置指纹、模型、collection、向量 ID、状态和错误；
  - `knowledge_projection_outbox`：compact ID 命令、幂等键、租约、重试和 DLQ 状态。
- resolver 顺序固定为 canonical exact → alias exact → 同来源既有人工决定 → lexical → embedding Top-K。
- exact/alias 和同来源人工决定可写 confirmed link；词法和向量候选始终 `pending`，不会自动改名、加别名或合并 Concept。
- Chroma 返回后再次用 SQL 校验 Concept 属于当前用户且 active/confirmed；外部或其他用户 ID 不会成为候选。
- 人工动作覆盖仅关联、关联并新增别名、新建 Concept 和忽略；同来源后续提及可复用用户决定，但不会隐式扩大全局 alias。

### 2. 可恢复知识投影

- 知识 collection 使用独立 base name 和模型/配置指纹，不与 Material retrieval chunk namespace 混用。
- Concept 快照固定包含规范名、别名和定义；Claim/Unit 只投影当前用户、当前来源版本、active 状态的 SQL 正文。
- outbox payload 只保存对象类型和 ID，consumer 处理时回读规范 SQL，不复制完整 Claim 或原文。
- 支持幂等 upsert、delete、按用户 `rebuild_user`、租约回收、有界重试和 DLQ；SQLite 单消费者，PostgreSQL 使用 `FOR UPDATE SKIP LOCKED`。
- Source 更新/删除会清除旧 Claim/Unit 向量；Concept create/rename/alias/review/split/merge/delete 会登记相应命令。
- embedding URL/模型/维度等配置变化会失效当前用户的旧投影；模型或维度变化切换 collection，并删除旧向量。全量重建从当前 SQL 枚举对象并清除孤儿，不依赖历史 outbox 完整存在。
- 缺少 Key、Chroma 不可用或超时时，任务以 `degraded` 收口且不阻塞业务事务；exact/alias 和 SQL 审核路径继续可用。

### 3. API、运行时与最小 UI

- 新增：
  - `GET /api/knowledge/resolution-candidates`
  - `POST /api/knowledge/resolution-candidates/{candidate_id}/resolve`
  - `POST /api/knowledge/projection/rebuild`
  - `GET /api/knowledge/status`
- extraction 成功保存 grounded Claim 后会登记 Claim 投影并解析概念提及；Material/Note 生命周期同时登记 Unit 投影和旧版本删除命令。
- 应用只在 `KNOWLEDGE_V2_ENABLED=true` 且 `KNOWLEDGE_EMBEDDING_ENABLED=true` 时启动独立知识 projection worker，健康接口暴露最小运行状态。
- 资料摘要增加待解析数。侧栏抽屉展示原 Claim/Evidence、解析建议和分数，支持关联、关联并新增别名、新建、忽略及进入既有概念合并页。
- 抽屉复用当前视觉系统，桌面宽度为 `520px`，窄屏不超过 `100vw`；真实 Chromium 已检查桌面和 `390px` 视口，未发现运行时控制台错误。
- 打包静态路径检查发现 FastAPI 的 CSP 比 Nginx 缺少 React/Ant Design 必需的内联样式许可；现已收敛到同一受限策略，保留 self-only script、禁止 object/frame，并只对样式开放 `'unsafe-inline'`。桌面实际使用的 `/dashboard` 静态入口复查后布局正常、内联样式违规为 `0`。

## 离线质量契约

`tests/fixtures/knowledge_resolution_rankings.json` 保存脱敏、记录式合成 embedding 排名；`evaluate_entity_resolution.py` 不初始化 provider、不访问网络：

```bash
cd backend
venv/bin/python evaluate_entity_resolution.py --summary-only
```

结果：

- 正例 `24`，Top-5 Recall `1.0`，门槛 `0.90`；Top-1 Recall `0.5`。
- 负例 `4`，准确率 `1.0`。
- 跨用户命中 `0`，自动语义合并 `0`，外部模型调用 `0`。
- 确定性摘要：`eb8e0c97b941282f9997b162b5b132668f1e5b15a5ae335830ba6b046baac71d`。

该结果验证排名、过滤和门禁代码的确定性，不代表真实 embedding provider 的召回质量，也不替代真实中英文资料或真人审核抽样。

## 验证结果

- Stage 0～3、迁移和事务关键组合专项：`64 passed`。
- 完整后端：`549 passed, 15 skipped, 58 subtests passed`。
- 前端：`27 test files / 93 tests passed`；TypeScript/Vite production build 和 ESLint 通过。
- 打包静态/CSP 安全专项：`12 passed`；真实 Chromium 静态入口样式复查通过。
- 全新 PostgreSQL 16：迁移到唯一 head `20260903_21`，候选门禁 `10 passed`，`alembic check` 无 drift。
- 历史 PostgreSQL 16 dump/restore：从旧迁移点恢复固定历史数据，经正式迁移入口升级到 head，数据保留专项 `1 passed`，`alembic check` 无 drift。
- 一次性 PostgreSQL 容器、SQLite UI 数据和截图均已清理。

## 发布轨道遗留事项

- 版本来源一致性 preflight 通过；当前正式版本仍为 `v1.3.0`，尚未选择下一候选版本。
- 候选 clean-tree preflight 按设计拒绝当前包含大量既存未提交改动的工作树；后续须按 Stage 1～3 文件选择性整理到干净提交。
- 本地环境没有 PowerShell 和 Windows 签名凭据，不能在此生成正式可接受的签名安装包。
- 远程候选 workflow、真实 Windows Electron 安装/升级/卸载 E2E、正式数据库冻结/快照/升级、tag、GitHub Release 与公开资产均未执行；这些动作需要新版本选择、干净候选提交、签名秘密、生产连接和发布窗口，不由本阶段擅自触发。

## 失败、降级与回滚

- `KNOWLEDGE_EMBEDDING_ENABLED=false` 会停止知识 projection worker；SQL Claim、解析候选、ClaimConceptLink 和人工决定不丢失。
- `KNOWLEDGE_V2_ENABLED=false` 会停止新的来源 hook、extraction 和解析产品入口，Association V1 保持原路径。
- Chroma 是可重建投影，故障或清空后可按用户从 SQL 重建；生产回滚保留新表，不执行破坏性 downgrade。
- `KNOWLEDGE_SEMANTIC_AUTO_RESOLVE_ENABLED` 仍不开放纯语义自动确认，避免误以为开关存在就允许自动合并。

下一开发阶段是 Stage 4：Association V2 + `SqlGraphStore`。它尚未启动，Neo4j/Graphiti 也仍只保留默认关闭的后续 Shadow 候选。
