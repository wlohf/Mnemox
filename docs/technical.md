# Mnemox 技术基线

> 状态：维护中
>
> 基线日期：2026-08-22
>
> 当前发布版本：v1.3.0
> 代码范围：post-v1.3 统一开发基线；包含 `RetrievalRouter`、资料 SQL 检索投影、Chroma 生命周期、可审核 SQL 概念图谱、版本化来源、人工身份治理、先修缺口、强弱证据融合、可解释推荐、projection outbox、ContextStore、Coach 联想归因、Vault 安全、SQL 记忆声明、Phase 2 的受控 AgentRuntime 纵向切片，以及 Mnemox V2 Stage 0～7 的 Claim、Association、Sparse/Reranker、图候选评测与 Stage 7 Optional Neo4j Runtime 地基。**Stage 6 已于 2026-09-04 完成：Neo4j / Graphiti 均不进入默认产品 Runtime。** Stage 7 Phase 0～2 已完成图领域语义、storage-neutral path DTO/方向契约、`GRAPH_BACKEND=sql|neo4j` selector、Projection lifecycle、readiness、fallback 与 rollout：Neo4j selector 会启用 `neo4j_graph` Outbox/worker target；图变更通过 rebuild-only dirty propagation 重新排队，同一用户使用 bounded two-slot coalescing 与跨进程串行锁避免丢更新/并发 rebuild；认证态 Knowledge Status 将 primary connectivity、projection initialization/caught-up、rollout 和 fallback serving readiness 分开表达。只有“命中灰度 + 已初始化 + 无 pending/processing/failed/DLQ + primary healthy”才尝试 Neo4j，否则基础读路径直接使用 SQL；Neo4j 查询报错再由 request-scoped fallback 降级。真实 disposable Neo4j 5.26 已通过 SQL parity、重复 rebuild、错误凭据、隔离、删除、无原文属性与 stale gate 验收；默认仍是 SQL。第一个 graph-native Knowledge/Learning Path V1 已完成：Neo4j 负责 bounded path traversal，产品响应回到 Canonical SQL 重载 Concept、ConceptEdge、LearnerEvidence、UserConceptState 与 provenance；Phase 3.2 Explainable Multi-hop Association V1 也已完成，作为排序后的 default-off enrichment 输出 presentation-safe structured explanation，不改变 Ranker。Graphiti Temporal Slice 已完成 reviewed `MemoryDeclaration` 的 model-free temporal projection、current/as-of、delete/rebuild 与 SQL rehydrate，但 benchmark 明确继续支持 default Runtime NO-GO。Stage 7 最终门禁为 Knowledge/Temporal 宽回归 `149 passed`、真实 Neo4j/Graphiti 专项 `6 passed`、前端 `27 files / 93 tests` + build/lint；Architecture Story 见 `2026-09-04-mnemox-v2-stage7-architecture-story.md`。AgentKernel 尚未替代现有 Planner。

本文件描述当前仓库中已存在的技术实现、运行边界和维护约定。历史方案位于 `docs/superpowers/` 和其他设计文档中；它们用于理解决策过程，不应替代本技术基线。

面向下一阶段的目标架构与候选技术边界见 [2026-08-03 学习智能底座架构决策](superpowers/specs/2026-08-03-learning-intelligence-foundation-architecture.md)（混合 RAG、概念图谱、时态记忆、学习者模型与 AgentRuntime）；执行顺序见 [路线图](roadmap.md)。本文件只把已合入或已验证的能力写入“当前实现”；未提交原型、待迁移能力和实验性方案必须明确标注状态。

## 1. 系统概览

Mnemox 是一个本地优先的 Web 应用，并提供 Windows Electron 桌面壳。

```mermaid
flowchart LR
    UI["React 18 + TypeScript + Vite"]
    Desktop["Electron Desktop Shell"]
    API["FastAPI API"]
    DB["SQLite (local) / PostgreSQL (production)"]
    Vector["ChromaDB"]
    Files["Local uploads"]
    AI["AI providers and web search"]

    Desktop --> UI
    UI -->|REST / SSE| API
    API --> DB
    API --> Vector
    API --> Files
    API --> AI
```

### 运行单元

| 目录 | 作用 | 关键入口 |
| --- | --- | --- |
| `frontend/` | React 学习工作台 | `src/main.tsx`、`src/App.tsx` |
| `backend/` | FastAPI API、学习业务与 AI 集成 | `app/main.py` |
| `desktop/` | Windows Electron 壳、更新与通知桥接 | `src/main.js` |
| `data/` | 本地 SQLite、上传文件、向量相关数据 | 运行时生成，不提交真实用户数据 |
| `release-manifest/` | 应用内更新清单 | `latest.json` |
| `scripts/` | 打包、发布、演示数据等维护脚本 | PowerShell/Python 脚本 |

## 2. 技术栈

| 层级 | 当前技术 |
| --- | --- |
| 前端 | React 18、TypeScript 5、Vite、React Router 6、Ant Design、Zustand |
| 前端数据与内容 | Axios、Dexie/IndexedDB、ECharts、Toast UI Editor、react-markdown、KaTeX |
| 后端 | Python 3.10+、FastAPI、Uvicorn、Pydantic Settings |
| 数据 | SQLAlchemy 2 Async、SQLite、PostgreSQL/asyncpg、Alembic |
| AI 与 RAG | OpenAI、Anthropic、Google GenAI、LlamaIndex、ChromaDB |
| 文件与分析 | PyPDF2、python-docx、pandas、NumPy、SciPy、openpyxl |
| 桌面端 | Electron、electron-builder、electron-updater |
| 测试 | pytest、pytest-asyncio、Vitest、Node test runner |
| 交付 | Docker Compose、Windows NSIS 安装包、GitHub Release 配置 |

## 3. 后端架构

### 3.1 应用入口与中间件

`backend/app/main.py` 创建 FastAPI 应用并负责：

- 应用启动和关闭时的数据库初始化、目录准备和资源清理。
- Episodic Memory 衰减。
- RAG 初始化、缺失资料投影补建，以及失败索引/删除墓碑的启动恢复。
- CORS、速率限制、请求大小限制和安全响应头。
- 请求参数校验错误的中文友好提示。
- 已认证上传文件的安全读取，以及可选的前端静态站点托管。

### 3.2 API 组织

当前后端包含 31 个路由模块，按 `/api/*` 前缀组织。主要领域如下：

| 领域 | 路由模块 |
| --- | --- |
| 身份与系统 | `auth`、`system`、`images` |
| 对话与 AI | `chat`、`conversations`、`chat_projects`、`ai_settings`、`prompt_templates` |
| 学习内容 | `materials`、`rag`、`notes`、`obsidian_import` |
| 计划与执行 | `goals`、`plans`、`study_sessions`、`pomodoro` |
| 练习与复习 | `wrong_questions`、`review`、`anki` |
| 洞察与画像 | `learning`、`analytics`、`profile`、`memory`、`motivation`、`interventions` |
| Agent 与 Coach | `agent`、`agent_memory`、`coach` |
| 学习者模型 | `learner_model`（状态、证据、人工修正、重算与投影重放） |

路由应保持薄：鉴权、请求/响应模型、状态码和领域调用可留在路由层；可复用业务规则、事务编排和 AI/RAG 集成应位于 `app/services/` 或 `app/ai/`。

### 3.3 数据与服务

- `app/models/`：当前有 25 个数据模型模块，覆盖用户、资料、章节、目标任务、学习事件、学习证据/概念状态、聊天、记忆、复习、Agent、Coach 等领域。
- `app/services/`：当前有 46 个服务模块，处理用户画像、事件、学习者模型、概念图谱、推荐、投影、记忆、搜索缓存、笔记上下文、Agent 学习、Coach 策略和检索等。
- `app/ai/`：多模型 Provider、模型路由、Prompt 组装、RAG、搜索和错误归一化。
- `app/agents/`：Agent 运行时抽象；业务上与 `agent`、`agent_memory`、`coach` 路由及相关服务协作。

### 3.4 数据流

```text
用户操作
  -> 前端 service API client
  -> FastAPI router
  -> service / AI / RAG
  -> SQLAlchemy 数据模型、ChromaDB 或上传文件
  -> 学习事件、记忆、画像与 Coach 策略
  -> REST 或 SSE 返回前端
```

聊天完成后的摘要、记忆、反思、错题检测和学习事件采用分阶段处理。某一后处理失败不能删除已保存的对话内容。

## 4. 前端架构

### 4.1 页面与导航

主业务页面位于 `frontend/src/pages/`，当前包含对话工作台、Dashboard、番茄钟、错题、复习、目标任务、计划、笔记、记忆、掌握度、进度引擎、用户画像、Prompt、EDA、干预、Agent 和 Anki。

除 `/login` 外，路由通过 `ProtectedRoute` 保护。主工作区布局由 `components/Layout/ObsidianLayout.tsx` 与相关导航、侧栏、今日聚焦组件组织。

### 4.2 前端数据边界

- `services/`：唯一的后端 API 调用入口。`apiClient.ts` 负责 Bearer Token、通用错误处理与 401 清理。
- `stores/`：Zustand 管理认证、聊天、番茄钟和主题等跨页面状态。
- `db/studyDb.ts`：Dexie 本地数据表定义。
- `sync/`：同步引擎、队列和模块适配器。当前离线优先范围包括笔记、目标、目标任务、错题和 Anki 卡片。
- `hooks/`：离线优先业务 Hook。

新增接口不应直接在页面中散落 `fetch` 调用；新增离线实体需同时定义本地表、入队逻辑、同步适配器、失败状态和用户可见的处理方式。

## 5. AI、RAG 与 Agent 边界

### 5.1 多模型与搜索

AI 设置支持 OpenAI、Claude、Gemini、DeepSeek/Qwen 及 OpenAI-compatible 服务，并可为聊天、复习、错题、Agent 和 Embedding 等场景配置路由。联网搜索可走 provider hosted search、Tavily、应用层搜索，并在失败时回退到 DuckDuckGo/Bing。

### 5.2 统一检索与 RAG 降级

资料、笔记、概念、记忆和学习者状态通过 `RetrievalRouter` 进入主聊天、ChatAgent、AgentKernel 与 `/api/materials/search`。资料后端固定为 `Chroma dense + SQL keyword + RRF`，先按当前用户、项目和资料范围授权，再融合结果并按 L0/L1/L2 装载证据。Embedding 不可用时保留规范 SQL 分块与关键词召回；单个来源故障不应破坏其他来源或使资料上传返回 500。

`retrieval_projections` 记录用户、来源类型/ID、后端、来源版本、已索引版本、embedding/分块配置指纹、状态、错误、尝试次数和时间戳；`retrieval_projection_chunks` 保存带用户、来源版本、序号和内容哈希的可重建 SQL 分块清单。领域资料和原始文件是规范来源，SQL 分块与 Chroma 向量均是派生投影。

```text
上传 / 更新规范资料
    -> SQL 分块清单与来源版本提交
    -> Chroma 向量生成
    -> ready / degraded / failed

删除规范资料 + 删除墓碑
    -> SQL 分块同步清除
    -> Chroma 按 user_id + material_id 删除
    -> deleted；失败时保留 failed 墓碑供 retry
```

`RetrievalProjectionService` 提供 `ingest`、`refresh`、`prepare_forget`、`forget`、`retry`、`rebuild_user` 和 `forget_user`；资料更新替换旧清单与向量，配置变化将旧投影标记为降级，服务重启恢复中断的索引或删除。资料侧栏显示单条状态、错误和重试，AI 设置显示当前用户的聚合状态。若 manifest 哈希与当前 SQL 正文不一致，关键词检索直接回退规范正文。

固定语料位于 `backend/tests/fixtures/retrieval_eval_cases.json`。`backend/evaluate_retrieval.py` 离线评测 Recall@5/10、MRR、NDCG@10、平均/P95 延迟、用户隔离、删除残留、空查询和无 embedding 降级；常规 GitHub CI 对生产 hybrid 设置 Recall@5 不低于 `0.75` 的门禁。选型证据见 [检索生命周期与质量 ADR](superpowers/specs/2026-08-22-retrieval-lifecycle-quality-adr.md)。

### 5.3 笔记上下文

聊天笔记检索保留 `note_context_service -> ContextStore`，并作为 note source 纳入 `RetrievalRouter`。当前 `KeywordContextStore` 对用户 SQL 笔记按标题、标签和正文匹配；资料 source 已完成独立 SQL chunk 投影、Dense/Sparse 融合、版本更新、删除恢复和离线质量集，但笔记尚未迁移到相同持久化 manifest。摘录经过 `wrap_untrusted_context` 包装并受字符预算限制；笔记来源故障降级为正常聊天，流式接口以 SSE 返回参考指示器。

### 5.4 Agent 与 Coach

- Agent 汇总目标、今日任务、逾期任务、复习、错题、笔记、用户画像和记忆，输出行动建议或写入草案。
- 当前稳定主路径仍是规则简报与一次性 Planner；多步只读 AgentKernel 已接入调试态前端入口，并持久化预备任务、短租约和受限上下文 checkpoint。每个工具/格式纠正步骤提交后保存下一步骤号与模型上下文；当前实例在检查取消和保存进度时续租。启动检查与生命周期回收器使用行锁和 `SKIP LOCKED` 只回收已过期租约，迟到旧实例因 owner 不匹配不能覆盖终态；回收器运行状态、轮询间隔和累计回收数以最小信息暴露在 `/health`。用户可从下一模型步骤精确续跑，取消中的中断仍收口为取消。独立 SSE 端点以短事务轮询用户自有的持久日志，实时订阅与断线回放不占用模型执行会话。完成任务的行动建议通过 `agent_action_confirmations` 保存用户、任务、行动快照、确定性草案和执行结果；确认请求只提交 32 字符凭据，服务端重新验证任务归属、终态、目标归属与状态，随后原子领取凭据、同事务创建任务/事件/审计，重复请求返回首次结果。续跑与写入均需要用户确认，系统不自动恢复 LLM 调用或执行写入；单次运行和逐用户 UTC 日预算按模型调用次数与供应商无关的估算 Token 在下一次调用前硬停止，失败/超时调用同样计数。成功响应会从 OpenAI-compatible、Claude 或 Gemini 的供应商 usage 归一化真实输入/输出 Token；真实、估算和未对账调用分开随 checkpoint/任务尝试持久化，恢复任务只累计新尝试。Provider 设置可保存用户自有的每百万输入/输出 Token 美元单价，两项齐全时用供应商 Token 计算参考成本，缺失时不猜价；该值不等同供应商发票。日归属优先使用任务实际启动时间，旧数据才回退创建时间。同一用户的 Kernel 启动通过 PostgreSQL 用户行锁串行化，避免并发绕过；Agent 页显示当日估算护栏、真实 Token 和配置单价参考成本。真实密钥/账单抽样核对和运行时框架对照尚未完成，因此不能视为已替代 Planner。AgentRuntime v0 在 PostgreSQL 服务端运行：用户明确开启定时评估后，按逐用户持久计划低频检查复习积压，完成、跳过与失败均落任务状态，失败采用有界重试；建议仍受 Coach 策略约束，不做自动写入或网页推送。
- AgentRuntime 调度时间统一存储为 naive UTC，API 输出为带 `Z` 的 UTC；`coach_preferences.time_zone` 保存经 `ZoneInfo` 校验的 IANA 时区。启动首轮会拾取下次时间为空或已经到期的 opt-in 用户；跨午夜免打扰命中时只把下次评估推进到本地结束点，不创建任务、事件或日志。学习快照的本地日使用 UTC 半开边界计算任务完成、番茄钟和 Coach 每日上限。每个用户周期有 `AGENT_RUNTIME_USER_TIMEOUT_SECONDS` 硬超时，取消事务后进入有界退避；PostgreSQL 使用 `FOR UPDATE SKIP LOCKED` 跳过另一实例正在处理的偏好行，并由用户/运行键唯一约束二次防重复。
- `COACH_INTERVENTION_EXPERIMENT_ENABLED` 默认关闭；开启时 `coach_experiment_service` 以 `SHA-256(experiment/version/user_id)` 生成 0–9999 的稳定桶，并按配置比例分为 control/shadow。v0 是严格 A/A 观察：两组使用完全相同的策略，`policy_applied=false`。实验 ID、分配版本、桶号、组别和模式会经类型/长度白名单写入 Coach 生命周期事件；用户 ID、标题、正文和自由文本不会进入实验载荷。`/api/analytics/coach-experiment` 只查询当前用户，按 7 天成熟归因窗聚合接受、开始、完成、领域事件完成、放弃和拒绝，单列 pending 与未埋点曝光，并固定返回未就绪；本层不修改策略分数，不提供 bandit。
- `weekly_learning_report_service` 将传入时间解释为 UTC，并用用户 IANA 时区计算周一 00:00 到下周一 00:00 的 UTC 半开自然周；即时报告扫描到生成时刻且包含该时刻。当前来源限定为当周更新笔记、当周完成复习和当周错题线索，每类最多保留最近 8 条；查询始终带 `user_id`，并排除 Obsidian `missing` 笔记。来源引用包含领域类型/ID、观察时间和内容版本指纹，连同结论与下一步生成 SHA-256 内容哈希和稳定草案键。返回的 Markdown 仅供用户审阅/复制；Obsidian active/conflict 均显式只读。周报调用快照时关闭画像加载，避免一次 GET 隐式计算并提交 `user_profiles`。当前未调用四层检索、未创建 `notes`、未提供 vault 写回接口。
- 长期记忆分为可审核候选、已确认、锁定、忽略等状态；敏感或主观推断应进入用户审核。
- 人工创建/修订和聊天提炼、会话反思、Agent 学习等自动路径都会写入 `MemoryDeclaration` 审计历史，保留来源、有效时间、置信度、审核状态、规则/模型版本和替代关系；`UserMemory` 继续承载当前产品投影。
- Coach 使用事件、用户偏好、每日上限、冷却和反馈统计选择是否触达及以何种渠道触达；`coach_action_attempts` 将一条建议和用户明确开始的行动关联起来。番茄钟开始/完成/中断、复习完成和已确认的日计划草案会写入真实领域事件并关闭该尝试；不能自动观察的动作只能由用户明确确认完成或放弃。建议回放返回触发、尝试和经过最小化的领域/Coach 事件时间线。
- Agent/Coach 的推荐必须能给出证据和风险理由；写入类操作必须走草案确认。

### 5.5 Mnemox V2 Stage 0～3：Canonical Claim、抽取、Entity Resolution 与知识投影

当前产品联想仍只有 Association V1：`association_service` 对当前用户已确认的 Concept 规范名和 Alias 做大小写不敏感的显式子串匹配，再查询一步 SQL 概念邻域并收集笔记/错题证据。Stage 3 已产生可审核的 Claim→Concept 语义锚点和知识向量投影，但 Association V1 尚不读取它们，也不包含 GraphStore、Claim 关系路径或知识 Sparse 投影，因此仍不能把隐含表达用于产品联想。

2026-09-02 完成的 V2 Stage 0 只固定后续实现的评测边界：

- `tests/fixtures/knowledge_extraction_eval_cases.json` 有 56 个脱敏合成 Unit，其中 50 个带人工 Claim 和精确原文 Evidence 标注；覆盖中英文、Material/Note、显式/隐含概念、反例、删除状态和跨用户哨兵。
- `tests/fixtures/association_v2_eval_cases.json` 有 56 个跨来源问题，显式/隐式与中英文各 28 个；每个正例都从 Material 形式的输入锚点指向另一 Note 来源，并覆盖同义词、反例、用户隔离与删除。
- `evaluate_knowledge.py` 在临时 SQLite 中直接调用现有 Association V1，不初始化 AI Provider、不访问网络。固定基线为：显式场景 Concept Recall@5/MRR 和来源 Recall@5/MRR 均为 `1.0`；隐式场景均为 `0.0`、无结果率为 `1.0`；跨用户违规和删除残留均为 `0`。结果 ID 摘要可跨运行比较，延迟保留每次实测值。

运行命令：

```bash
cd backend
venv/bin/python evaluate_knowledge.py --min-explicit-recall-at-5 0.95 --summary-only
```

V2/图实验开关继续默认关闭：`KNOWLEDGE_V2_ENABLED`、`KNOWLEDGE_LLM_EXTRACTION_ENABLED`、`ASSOCIATION_V2_ENABLED`、`ASSOCIATION_V2_SHADOW`、`KNOWLEDGE_SEMANTIC_AUTO_RESOLVE_ENABLED`、`NEO4J_GRAPH_ENABLED`、`NEO4J_GRAPH_SHADOW`、`GRAPHITI_ENABLED`、`GRAPHITI_SHADOW`；Stage 7 另新增默认值为 `sql` 的 `GRAPH_BACKEND=sql|neo4j`，它是产品 GraphStore 选择器，与历史 Shadow/Enabled flags 分离。Neo4j 可选运行时还有 `NEO4J_GRAPH_ROLLOUT_PERCENT`（0～100，默认 100，仅在明确选择 Neo4j 时生效）和 `NEO4J_GRAPH_ROLLOUT_USER_IDS`（逗号分隔 canary 用户 ID）；百分比采用稳定 SHA-256 user bucket，allowlist 可显式放行 canary，但二者都不能绕过 Projection readiness。Stage 3 另有默认关闭的 `KNOWLEDGE_EMBEDDING_ENABLED`；总开关控制来源、抽取和解析，embedding 开关单独控制知识 projection worker。选择 `GRAPH_BACKEND=neo4j` 时会同时把 `neo4j_graph` 纳入知识 Projection Outbox/worker target；缺少 Neo4j 凭据 fail closed。`KNOWLEDGE_SEMANTIC_AUTO_RESOLVE_ENABLED` 仍不执行自动语义合并；Stage 4 的 `/api/knowledge/associate` 只有在 `KNOWLEDGE_V2_ENABLED` 与 `ASSOCIATION_V2_ENABLED` 同时开启时可用，V1 保持不变。

抽取安全默认值为 Unit `8,000` 字符、每 Unit `12` 个 Claim、Claim `500` 字符、结构化输出 `12,000` 字符、每次调用 `30` 秒、每 Run `64` 次模型调用与 `64,000` 估算 Token、每用户每日 `256,000` 估算 Token。Stage 2 已在 LLM 调用边界执行长度、调用次数、run/日 Token 与超时限制；确定性 extractor 不调用模型。

Stage 1 新增 `knowledge_sources`、`knowledge_source_revisions`、`knowledge_units`、`claims` 和 `claim_evidence`。Source 用 `user_id + source_type + source_record_id` 保持稳定身份；Revision 保存内容哈希并以部分唯一索引保证每个 Source 最多一个 current；Unit 使用有界字符切片和 JSON locator；Claim 在来源版本内用规范化 SHA-256 指纹去重，数据库默认审核状态保持 `pending`，手工服务只在 Evidence 定位成功后显式确认；Evidence 保存摘录和精确字符范围。服务层只 `flush`，事务由 Material/Note/Obsidian/Agent 等调用入口拥有。

`KNOWLEDGE_V2_ENABLED=true` 时，Material 和 Note 创建/更新会登记版本；内容不变复用 current revision，内容变化将旧 revision 和 active Claim 标为 superseded。领域删除前会 tombstone Source/Revision/Claim，并清空 Unit、Claim 和 Evidence 正文。手工 Claim 只能绑定同用户 current revision 的 Unit，Evidence 必须能在 Unit 中精确定位；可见查询再次校验用户、active Source、current Revision、active/reviewed Claim 及 Evidence 存在。默认开关为 false，因此现有数据库不会自动回填，Association V1、Concept、Memory、LearnerState 和 Chroma 行为不变。

Stage 2 新增严格 `KnowledgeExtractionResult` Schema、`DeterministicKnowledgeExtractor` 与 `LLMKnowledgeExtractor`。LLM 优先使用 Provider 可选 strict structured output，不支持时回退 JSON 并用同一 Pydantic 模型验证。Grounding 先做精确匹配，再做 NFKC、空白和标点归一匹配，最终保存原始字符范围；没有 Evidence 或无法定位的候选不写入。自动 Claim 全部为 `pending`，来源版本内按指纹幂等，重叠 chunk 的 Evidence 按绝对来源位置去重。

`knowledge_extraction_runs` 保存 extractor/schema/provider/model/input 身份、状态、尝试、可用时间、租约、脱敏错误、usage 和统计；唯一键保证同一输入只建一个 run。worker 以短事务取得租约，PostgreSQL 使用 `FOR UPDATE SKIP LOCKED`，SQLite 只启一个应用内消费者；过期租约可回收，失败有界退避，用户可查询、重试或取消。每个 Unit 在 savepoint 中处理，局部失败得到 `partial` 且不撤销成功 Unit。Material/Note 在总开关开启时创建确定性 run，LLM run 还要求独立开关；缺少 AI Key 只使 LLM run 失败。资料 API/UI 仅暴露状态和 pending 数量。

Stage 3 的 `entity_resolution_candidates` 保存 mention、关系类型、候选 Concept、exact/alias/lexical/vector/context/combined 分数与审核决定；`claim_concept_links` 只在 exact/alias、既有同来源人工决定或本次用户审核后建立 confirmed 链接。resolver 先查 canonical exact，再查 alias exact，再复用同来源人工决定，随后才计算词法与可选 embedding Top-K；所有向量结果必须回 SQL 确认 Concept 仍属于当前用户且 active/confirmed。词法或纯语义命中只创建 `pending` 候选，不自动新增别名、重命名或合并 Concept。

`knowledge_embedding_projections` 为 Concept、Claim、Material Unit、Note Unit 保存对象内容哈希、embedding 配置指纹、模型、collection、向量 ID、状态、尝试和脱敏错误。知识 collection 以独立 base name 与模型/配置指纹命名，不与资料 chunk collection 混用。`knowledge_projection_outbox` 只保存用户、对象 ID、操作、幂等键和租约/重试状态，不复制完整 Claim 或原文；consumer 回读当前 SQL 快照并执行 upsert/delete/rebuild_user。更新、删除、Concept rename/alias/merge/delete 和 embedding 配置变化都会登记命令；全量重建从当前 SQL 枚举有效对象并删除孤儿，模型或维度变化会切换 collection 并清理旧投影。

`GET /api/knowledge/resolution-candidates`、`POST /api/knowledge/resolution-candidates/{candidate_id}/resolve`、`POST /api/knowledge/projection/rebuild` 和 `GET /api/knowledge/status` 均受总开关和当前用户约束。资料侧栏的概念解析抽屉支持仅关联、关联并新增别名、新建 Concept、忽略以及进入已有概念合并页。Chroma、Key 或超时故障只使 projection 标记为 `degraded` 或语义候选回退，不影响 exact/alias、SQL Claim、候选列表和人工审核。

记录式合成 embedding 排名 fixture 包含 24 个正例和 4 个负例，固定 Top-5 Recall `1.0`、门槛 `0.90`、Top-1 `0.5`、负例准确率 `1.0`，跨用户命中、自动语义合并和外部模型调用均为 `0`。该 runner 只验证确定性排序、过滤与门禁契约，不代表任何真实 embedding provider 的质量；启用具体 provider 前仍需用真实中文/英文样本抽验。

完整分阶段设计见 [Mnemox V2 Claim 中心知识图谱实施设计](superpowers/specs/2026-09-02-mnemox-v2-claim-centered-knowledge-graph-implementation.md)。Stage 4 已加入 ClaimRelation、`GraphStore` protocol、默认 `SqlGraphStore`、`association_v2_service` 和 `/api/knowledge/associate`；Stage 5 已完成 auto Sparse、claim-level dirty/outbox、reference fallback 和可选 LLM reranker。Stage 6 最终证据见 [2026-09-04 Stage 6 Go/No-Go](superpowers/specs/2026-09-04-mnemox-v2-stage6-final-go-no-go.md)：Neo4j 1000/5000 Claim 的 ID/path/score 一致率均 `1.0`，5000 combined p95 `33.97ms → 19.20ms`，但 direct 无稳定收益且新增约 `0.7–1.0 GiB` 内存、`~0.52 GiB` 数据盘及双后端运维；Graphiti 0.30.1 的真实 Neo4j BM25-only/as-of/group-scope 门禁通过，100/1000 facts Recall@5 与 SQL 均 `1.0`，但 p95 `14.24/19.15ms` 慢于 SQL `8.28/9.62ms`。因此二者不作为默认产品 Runtime。后续增量方向见 [图架构演进 ADR](superpowers/specs/2026-09-04-mnemox-v2-graph-evolution-and-portfolio-architecture.md)：Neo4j 作为可选 Graph Backend 建设，承载 Knowledge/Learning Path 与 Explainable Multi-hop；Graphiti 只做独立 Temporal/Episodic Slice。离线 56-case Association 合成集显式/隐式 Recall@5 均为 `1.0`；Stage 4 真实人工牵强率与产品灰度仍单列待验收。

## 6. 目标学习智能底座（部分已实现）

本节是工程目标与真实实现状态的对照，不是当前默认部署拓扑。产品运行时仍以 SQLite/PostgreSQL、Chroma、Sparse/关键词降级、SQL 概念表、`UserMemory` + `MemoryDeclaration` 和原生 Agent/Coach 为主；Qdrant、LangGraph、Neo4j、Graphiti 均不是默认运行时依赖。Stage 7 已把 `create_graph_store()` 从“永远返回 SQL”演进为显式 `GRAPH_BACKEND=sql|neo4j` selector，并完成 query-time fallback、projection initialization/caught-up health gate、稳定用户灰度、rebuild dirty propagation 与真实 Neo4j parity；默认值仍是 SQL，因此这表示“可选 server backend 基础可运行”，不表示已经全量生产切流。graph-native `find_concept_paths()` / Knowledge Path V1 已完成并通过真实 Neo4j integration；Explainable Multi-hop V1 也已完成。Graphiti Temporal Slice 也已完成 reviewed `MemoryDeclaration` → deterministic Graphiti projection → BM25 current/as-of → SQL rehydrate；60/300 temporal declarations benchmark 的 SQL/Graphiti correctness 均为 `1.0`，但 Graphiti p95 `192.20/138.55ms` 显著慢于 SQL `4.77/2.92ms`，因此仍只作为 Experimental/default-off。后续真实中文/双语人评和长期灰度指标通过 WebUI dogfooding 补齐。学习者模型与记忆声明产品切片继续使用 SQL，不依赖候选组件。

```mermaid
flowchart LR
    SQL[("SQL 规范数据<br/>SQLite / PostgreSQL")]
    Files["原始文件<br/>本地 / BlobStore"]
    Events["LearningEvent + Outbox"]
    Context["ContextStore<br/>资料证据"]
    Graph["ConceptGraph / GraphStore<br/>知识关系"]
    Memory["MemoryStore / TemporalMemoryGraph<br/>用户变化"]
    Learner["LearnerModel<br/>证据与状态"]
    Runtime["AgentRuntime / Coach<br/>编排与治理"]

    Files --> SQL
    SQL --> Events
    Events --> Context
    Events --> Graph
    Events --> Memory
    Events --> Learner
    Context --> Runtime
    Graph --> Runtime
    Memory --> Runtime
    Learner --> Runtime
```

### 6.1 规范数据与可重建投影

| 领域 | 当前实现 | 目标规范来源 | 允许的专用投影 |
| --- | --- | --- | --- |
| 资料与片段 | 上传文件、SQL `Material`、版本化 SQL chunk 清单和 Chroma | 原始文件 + SQL `Material` | `retrieval_projections`、SQL chunk 清单、Chroma 向量；均可按用户重建或删除 |
| 笔记 | SQL `Note` Markdown、标签、关联和 `source_path`；另有关键词检索路径 | SQL `notes`（Mnemox 内部原文、归属与更新时间） | `ContextStore` chunk/关键词/向量/摘要；概念关系与记忆候选仅作带来源派生数据 |
| Claim 知识 | `knowledge_sources`、不可变 Revision、可定位 Unit、Claim/Evidence、durable extraction run、解析候选、ClaimConceptLink、四类 embedding 元数据与 compact outbox；支持手工 Grounding、自动 pending Claim 和可审核概念锚点 | SQL `Material`/`Note` + Canonical Claim/Run/Resolution/Projection 表 | 独立 Chroma + dialect Sparse 已作为可重建投影接入；Neo4j/Graphiti 仅为 Stage 6 默认关闭 Shadow，均不得成为唯一来源 |
| 知识关系 | `concepts`、`concept_edges`、`concept_links`、`concept_aliases`、`concept_source_evidence`、`concept_audit_events`，以及 Stage 3 的 confirmed ClaimConceptLink | SQL 中带用户归属、来源版本、置信度、审核状态和人工操作历史的概念图 | `GraphStore`（Neo4j 等，仅在真实 SQL 多跳不足后评估） |
| 长期记忆 | `UserMemory` 当前投影、带事实键/唯一约束/冲突审核/有效期的 `MemoryDeclaration` 审计历史、会话摘要与事件 | SQL 中带来源、有效时间、冲突处理、人工纠错和替代关系的记忆声明 | Graphiti 时态记忆图（仅在出现真实 SQL 能力缺口且 Spike 通过时评估） |
| 学习能力 | `learner_evidence` 不可变证据、`user_concept_state` 可重算状态；`Concept.mastery` 仅兼容读取 | SQL `learner_evidence` / `user_concept_state` | 分析视图/缓存；不得把状态只留在图或向量库 |
| Agent 运行 | Planner、`AgentJob`、`AgentActionConfirmation`、草案确认 | SQL 中的运行、checkpoint、租约、行动快照、确认结果和审计记录 | LangGraph checkpoint 等运行态存储（若 Spike 通过） |

所有投影必须记录 source/version/namespace、幂等键、消费状态和错误。用户删除、资料更新或权限变更先更新规范来源，再由 outbox 刷新或清除投影；投影可从 SQL 和原始文件重建。

### 6.2 目标领域接口

| 接口 | 负责的能力 | 当前状态 |
| --- | --- | --- |
| `BlobStore` | 原始文件、版本、删除与读取授权 | 需要从现有本地上传抽象出来 |
| `RetrievalRouter` / `ContextStore` | 跨来源查询、范围过滤、混合召回、分层加载、删除 | Router 已统一资料/笔记/概念/记忆/学习状态；资料具备版本化 SQL/Chroma 投影和完整生命周期；笔记仍使用可降级 SQL ContextStore |
| `ConceptGraph` / `GraphStore` | 关系维护、来源、邻域/路径查询、人工修正 | SQL 图谱已存在；独立图存储尚未评估 |
| `MemoryStore` / `TemporalMemoryGraph` | 记忆声明、时间有效性、冲突/失效、相关记忆检索 | SQL 已覆盖事实唯一性、冲突审核、确认替代、纠错原因、自动失效、全入口过滤和派生删除；筛选 episode 图投影只在真实需求成立后评估 |
| `LearnerModel` | 证据记录、状态聚合、遗忘风险、下一步建议 | `learner_model_service` 与 `learning_recommendation_service` 已完成强弱证据、练习计数、FSRS/目标/先修解释型推荐、API 和前端下钻；真实 holdout 校准待积累 |
| `AgentRuntime` | 运行、流式、暂停/恢复、取消与工具编排 | 原生 Kernel 已具备持久任务、短租约/过期回收、受限上下文 checkpoint、用户确认的下一步精确续跑、SSE 实时订阅/断线回放、取消/安全重试、预算护栏、供应商真实 Token/配置单价参考成本对账和持久凭据保护的幂等行动确认；opt-in 复习积压 worker 已具备逐用户计划、启动 catch-up、时区/免打扰、单用户超时、多实例跳锁和有界重试。真实账单抽样、远程 PostgreSQL 验收和 LangGraph 对比仍未完成 |

接口只定义业务语义，不泄露 Qdrant、Neo4j、Graphiti 或 LangGraph 的类型到 Router/页面层。领域服务永远负责鉴权、权限过滤、草案确认、审计和业务事务。

### 6.2.1 笔记的三层存储与三阶段检索

笔记采用三层逻辑存储，不要求三套物理数据库：

1. SQL `notes` 是原始 Markdown、标题、标签、归属、关联和更新时间的规范来源。
2. `ContextStore` 承载可重建的 chunk、关键词/稀疏索引、向量、摘要和索引版本。
3. 概念关系、记忆候选和学习证据引用是独立派生数据，必须携带 `user_id + note_id + source_version`；不得覆盖原文或直接改写掌握度。

查询顺序固定为“路由与范围过滤 -> 混合召回 -> 重排与 L0/L1/L2 分层加载”。聊天笔记检索现已只依赖 `ContextStore`，当前 `KeywordContextStore` 直接查询 SQL，因此 `ingest/forget` 是幂等 no-op；这完成了接口边界和用户隔离的首条迁移，但不代表独立索引、Dense/Sparse 混合召回或更新/删除闭环已经完成。完整语义和剩余验收见 [2026-08-13 决策](superpowers/specs/2026-08-13-note-context-memory-architecture.md)。

目标生命周期：

```text
Note 写入/更新 + LearningEvent + outbox
  -> ContextStore ingest/refresh
  -> 可选概念关系与 staged 记忆候选

Note 删除/失效
  -> ContextStore forget
  -> 清理 chunk/向量/缓存
  -> 删除或失效来源派生数据
```

检索输出至少包含 `source_type=note`、`source_id`、标题、命中摘录、检索模式、内容/索引版本和降级状态。更新后不得召回旧版本，删除后不得在关键词、向量、缓存、图谱或未确认记忆候选中留下可检索残留。

### 6.3 学习证据与状态的当前切片

学习事件是原始事实，学习证据是可重放的模型输入，学习者状态是可再计算的派生结果。本轮已新增并通过 SQLite/Alembic 迁移验证：

```text
learner_evidence
  user_id, concept_id, evidence_type, evidence_category, dimension,
  score, reliability, source_event_id, observed_at,
  source_type, source_id, model_version, payload_version, payload

user_concept_state
  user_id, concept_id, mastery_estimate, confidence,
  forgetting_risk, attempt_count, correct_count, hint_count,
  mastery_dimensions, common_error_type,
  last_evidence_at, last_reviewed_at, next_review_at,
  manual_override, source_event_id, reliability, model_version,
  explanation_summary, updated_at
```

`learner_model_service` 将证据类型限制为直接证据（`answer`、`recall`、`explanation`、`application`、`hint_count`、`review_result`）、间接信号（`study_duration`、`study_frequency`、`repeated_question`、`interruption`、`recovery`）以及 `legacy_mastery` / `manual_override`。直接证据按可靠度和 90 天半衰期加权；通常 `score` 越高表示表现越好，`hint_count` 的原始分数则表示提示依赖度并在聚合时显式反转。间接信号只调整置信度和遗忘风险，解释摘要明确记录其影响，不能单独提高掌握度；答题、正确和提示计数从可回放证据重新派生。复习中心及错题复习共用 FSRS 优先调度，并在同一事务内回填 `review_result`。人工修正也写事件和证据，重算时保留直到用户明确清除。Graphiti 的记忆检索可以提供带来源的学习上下文，但不得写成唯一的 mastery 输入。

SQL 概念图额外保存别名、来源证据、审核状态和操作审计。资料创建/更新后，本地解析标题、定义、标记词、括号别名和明确先修箭头，不调用 LLM；自动结果处于 `pending`，只有人工确认后的节点与关系可以进入先修遍历和推荐。资料来源版本变化时清理旧摘录及仅由旧资料支持的自动关系；人工概念、其他来源及已有学习证据保持不变。概念支持改名、别名、合并、拆分、删除，合并迁移挂接、关系、来源、学习证据、错题和 outbox；所有关系校验当前用户并阻止先修环。

`learning_recommendation_service` 只读组合确认后的概念图、状态、活跃目标、错题和 FSRS 到期项，生成到期复习、先修补缺、无提示回忆、针对性练习和目标推进五类候选；固定公式为 `0.28×风险 + 0.20×目标 + 0.24×先修阻塞 + 0.16×错误 + 0.12×紧迫 - 0.12×疲劳`。每条建议提供中文原因、分项得分、证据 ID、目标、阻塞概念与 FSRS 来源，不直接执行用户数据写入。完整契约和 Neo4j no-go 见 [概念图谱与学习推荐 ADR](superpowers/specs/2026-08-22-concept-graph-learning-recommendations-adr.md)。

SQL 时态记忆以 `user_id + fact_key` 识别事实，并使用条件为 `review_status = 'confirmed' AND valid_to IS NULL AND fact_key != ''` 的部分唯一索引保证同一事实只有一条开放的已确认声明。自动矛盾值进入 `staged` 并关联 `conflicts_with_id`；旧事实在人工确认前保持生效。用户接受候选会在同一事务内关闭旧事实并设置 `supersedes_id`；拒绝、纠错和到期分别保留 `resolution_reason`。过期值在统一检索、聊天、Coach、Agent、反馈排序与学习快照的 SQL 入口均被过滤；用户纠错、删除、替代或失效会移除引用旧事实的 `agent_core_profile`。完整契约和 Graphiti 暂缓依据见 [SQL 时态记忆生命周期 ADR](superpowers/specs/2026-08-23-temporal-memory-lifecycle-adr.md)。

迁移 `20260804_01` 将每个既有 `Concept.mastery`（0–100）复制为可靠度 0.35 的 `legacy_mastery` 证据，并初始化同值的 `user_concept_state`；`20260804_02` 新增 `projection_outbox`，`20260804_03` 对已验证的 v1.3 SQLite 漂移做条件式对齐，`20260809_05` 新增 Outbox 运维状态，`20260812_06` 为未完成队列聚合新增部分索引；`20260816_07` 与 `20260816_08` 增加 Vault 稳定身份、同步状态和冲突候选，`20260816_09` 增加可审计记忆声明，`20260822_10` 增加资料检索投影及版本化 SQL chunk 清单，`20260822_11` 增加概念审核、别名、来源证据、操作审计及学习状态计数，`20260823_12` 增加记忆事实键、冲突关联、处理原因、历史重复清理和当前事实部分唯一索引，`20260826_13` 增加 Coach 建议开始与未继续的反馈统计，`20260826_14` 新增 Coach 行动尝试及番茄钟关联字段，`20260827_15` 增加账号会话版本与持久登录节流状态，`20260830_16` 增加 AgentRuntime 逐用户调度和任务生命周期，`20260901_17` 增加用户级 Provider 输入/输出 Token 单价，`20260901_18` 增加 Coach IANA 时区，`20260902_19` 增加 Canonical Claim 的 Source/Revision/Unit/Claim/Evidence 五表，`20260903_20` 增加 durable knowledge extraction run，`20260903_21` 增加 Entity Resolution、ClaimConceptLink、四类知识 embedding 元数据和 compact projection outbox。SQLite 本地启动通过 lightweight migration 执行增量 DDL 和一次性回填，并用 `mnemox_lightweight_migrations` 记录状态；PostgreSQL 只通过 Alembic。

默认 SQLite 的 lightweight migration 与 Alembic 迁移链已覆盖到 head `20260903_21`。此前学习者模型收口备份为 `backend/data/backups/study-pre-slice-close-20260805-085415.db`，SHA256 `28AF023FD4950BE191389B57C097698653BC3E2AEB0937907B04CD0DD3221AB8`，与当时 `study.db` 一致。源库包含 16 个用户、19 条学习事件和 0 个概念，因此 legacy 证据和状态均为 0；outbox 也为 0，因为 schema 迁移不会为历史事件自动创建任务，历史投影必须显式触发 replay。Stage 1～3 不自动回填历史 Material/Note，只有打开总开关后的新写入或后续显式重建才登记 Source、run 和知识投影。早期步骤见 [数据库升级演练报告](database-rehearsal-2026-08-05.md)，既有发布演练见 [PostgreSQL 发布演练报告](postgres-release-rehearsal-2026-08-28.md)，Stage 3 本地历史恢复证据见 [Stage 3 验收记录](updates/2026/2026-09-03_mnemox-v2-stage3.md)。

一次性 PostgreSQL 16 演练库已从历史版本升级并验证 Phase 1 数据保留：用户、资料、笔记、概念和学习事件保留，可靠度 0.35 的 legacy 证据与状态按预期生成。CI 除启动 PostgreSQL 16 空库、验收真实 `SKIP LOCKED`、共享策略升级、双 worker exactly-once、独立心跳和 `alembic check` 外，还会从 `20260801_01` 写入固定历史数据，执行 custom-format dump/restore，再通过生产入口升级到代码 head 并核对数据。2026-08-28 当前部署的 `20260826_14` dump 已在一次性恢复库成功升级到 `20260827_15`，schema drift 为零且稳定数据量不变；临时库已删除，源库仍保持 `20260826_14`。正式发布窗口仍需在快照保护下显式升级源库，并核对生产数据、Vault、记忆声明、检索投影 schema 和回滚准备；生产回滚依赖升级前快照与应用版本同步回退，不使用自动 downgrade。

### 6.4 事件与投影流

时间契约以 `app/utils/utc.py` 为唯一共享转换入口：SQL 时间列继续保存 naive UTC，以兼容当前 SQLite 与 PostgreSQL schema；naive 入参被明确解释为 UTC，aware 入参先 `astimezone(UTC)` 再转换为数据库形态，禁止直接删除偏移量。跨 API、事件、审计和 worker 健康快照统一序列化为 RFC 3339 `Z`。Agent、Coach、`LearningEvent`、记忆声明、画像、学习快照、检索投影和 projection outbox 已迁移到该契约；UTC 日预算和无用户时区的 Agent“今天”使用 UTC 日历日。Coach 免打扰、本地自然日/周仍由 IANA 时区计算 UTC 半开区间。`north_star_metrics_service` 对既有 naive 历史事件保留显式墙上时间兼容语义，未经独立数据迁移与历史结果核对不得直接改写。

错误边界以 `app/utils/error_safety.py` 统一处理。`redact_sensitive_text` 在长度截断前识别 Authorization/Bearer、敏感键值、URL userinfo/查询密钥、常见云/AI Token、JWT 和私钥块，再折叠控制字符与换行；`safe_exception_summary` 只保留异常类型和脱敏摘要。`SafeErrorDiagnostic` 在此基础上保存调用方定义并规范化的错误码、已脱敏摘要，以及对“错误码 + 安全摘要”计算的 16 位 SHA-256 关联指纹；原始异常和密钥不参与指纹。Agent 失败任务/执行日志、Planner、AgentKernel、RAG、检索投影、projection outbox/DLQ、调度/回收 worker 和相关 AI API 已接入，持久字段按列上限保存，运维与用户读取边界再次脱敏。公开 worker 健康状态继续删除异常正文，但保留错误码和指纹供聚合；检索和 RAG 保留原有可操作说明以兼容前端。`[REDACTED]` 占位符的二次脱敏已保证幂等，因此写入/读取边界不会改变关联结果。关键路径不记录原始异常 traceback，避免 traceback 末行绕过消息脱敏。错误码按恢复动作定义，不以异常类名自动生成；HTTP 全领域错误目录仍是后续工作。

历史存量通过 `diagnostic_maintenance_service` 显式治理：只扫描失败任务/失败或重试日志的已知诊断字段，以及 outbox/检索投影的 `last_error`，不递归进入业务 payload。服务按主键游标分页，dry-run 只生成无正文聚合计数，apply 逐页 flush 且不 commit；`sanitize_diagnostics.py` 默认回滚预览，只有 `--apply` 才由命令入口提交整批事务。错误摘要变化时会同步修正已有结构化诊断指纹，重复运行保持零变化。该工具不替代读取边界，也不覆盖外部日志、备份和导出的保留治理。

Pydantic 部分更新语义统一通过 `app/utils/pydantic_compat.py` 读取显式提供字段：v2 优先使用 `model_fields_set`，只有属性不存在的 v1 环境才访问 `__fields_set__`。目标/任务、对话和笔记入口已迁移，避免 `getattr` 默认参数提前求值触发 v2 弃用警告，同时继续区分“未传字段”和“显式 null”。移除 Pydantic v1 支持前不得删除兼容分支，但新代码不得直接读取旧属性。

事务所有权遵循“入口拥有 commit/rollback，领域/投影服务只 flush”的 unit-of-work 契约。首批收口对象为用户画像与 Agent 只读工具：`compute_and_save_profile` 与内部 upsert 不再提交会话，`get_or_compute_profile` 在 savepoint 中隔离刷新失败，后台番茄钟画像刷新显式提交/回滚；`build_learning_snapshot` 只读取已有画像，因此 Agent、Coach 和周报的上下文组装不会隐式落库。画像 upsert 在 PostgreSQL/SQLite 上使用 `user_id` 冲突更新，消除同一用户首次并发生成时的“先查后插”竞争；冲突更新集合只包含该聚合器拥有的统计字段，不覆盖学习风格或 AI 评估等其他生产者字段。`AgentManager.call_chat_tool` 查询后只 flush 审计日志，HTTP 工具入口由请求依赖提交，AgentKernel 则随 checkpoint 事务提交，工具本身不能提前提交调用方状态。`app/utils/transaction_policy.py` 只登记跨外部存储的恢复检查点和独立 worker 两类所有者；AST 门禁双向核对 `app/services`、`app/agents` 的全部 `.commit()` 与该清单，因此新增隐式提交和迁移后遗留的宽松白名单都会失败。已登记的资料/检索 saga 仍需按调用链逐项补失败注入，不能把“登记”误解为原子性证明。

检索投影的稳定身份由 `uq_retrieval_projection_source_backend` 仲裁。PostgreSQL 和 SQLite 的 `_ensure_projection` 均直接执行原子 `ON CONFLICT DO NOTHING`，再按用户、来源类型、来源 ID 和后端读取唯一生命周期行；不再通过应用层“先查后插”决定首次创建。该改动不改变现有向量 saga 检查点，长耗时索引操作的顺序保护仍由独立 fencing 模块负责。

检索长操作通过 `app/utils/operation_lock.py` 建立两层 fencing：所有用户变更先取得全局配置共享锁，再取得同用户锁。SQLite 和单进程路径使用弱引用进程锁及写者优先异步读写锁；PostgreSQL 以 namespace/身份的稳定 signed BIGINT key 在独立连接上持有 session advisory lock，使 `RetrievalProjectionService` 可以跨 manifest/终态 commit 保持顺序。全局 RAG 配置的保存、热重载和旧 projection 失效则持排他锁，因此不会与 ingest、forget 或 rebuild 交错；不同用户仍可并行。退出时必须显式 unlock，取消时等待 unlock，失败时 invalidate 物理连接，避免锁随池连接泄漏。`ingest` 取得锁后以 `populate_existing` 重读规范资料；`rebuild_user`、`forget` 和 `forget_user` 共用同一用户边界，内部调用使用已锁定实现避免重入死锁。

目标写入顺序为“领域数据 + `LearningEvent` + `projection_outbox` 同一事务提交 -> 幂等消费者投影”。`record_learning_event` 现在会在同一 SQLAlchemy 事务中创建 outbox 行；`ProjectionOutbox` 具备用户/概念范围、幂等键、模型/载荷版本、`pending/processing/processed/failed` 状态、尝试次数、锁定时间、错误信息和可用时间。`projection_outbox_service` 支持重复消费、崩溃后回收、指数退避、按用户/概念/时间范围重放和状态重建；Review/Anki 完成复习会在请求事务内只消费对应 `source_event_id` 的投影，失败仍保留为可恢复 outbox 行。删除用户或概念会级联清理 outbox、证据和状态。

当前工作区已验证数据库原子幂等入队、所有可领取状态的最大重试限制、显式重放重置、概念级状态串行锁、525 条事件游标分页重放、跨用户/跨概念隔离和严格 API 输入边界。应用生命周期在 PostgreSQL 上会启动一个可配置 worker；一轮最多处理配置批量，但每条任务使用独立 session，在自己的事务内认领、投影并提交，避免多实例跨概念锁交叉，关闭数据库前优雅停止。全局 worker 直接以 PostgreSQL `FOR UPDATE SKIP LOCKED` 认领任务，使并发实例能跳过忙行并继续分配其他用户工作；认领后按用户排序取得 transaction advisory lock。用户范围 API/replay 先取得其用户 advisory lock，再领取行；其行锁冲突同样使用 `SKIP LOCKED` 跳过。SQLite/桌面端因仍保留请求内事件级消费而明确停用常驻 worker，避免无行锁数据库出现双消费者。`OUTBOX_WORKER_ID` 是可配置的逻辑前缀，每个运行时都会持久化独立的心跳 ID；受保护的 `/internal/outbox/metrics` 聚合未完成队列、跨实例活跃/轮询失败 worker、DLQ 和告警，不返回任务载荷或异常正文。`/health` 只返回不含主机标识和异常正文的本实例累计统计，并保留最近一次持久投影失败时间；SQLite 会标记 `sqlite_single_consumer`。真实 PostgreSQL 16 多实例门禁已在 GitHub CI 通过；正式生产升级仍是独立发布收口项目。

学习者模型 API 位于 `/api/learner-model`：概念状态及解释、分页/幂等证据、只读推荐、人工修正/撤销、单概念或批量重算、按用户/概念/时间范围重放，以及用户隔离的 outbox 入口均已提供。`/api/concepts` 同时支持详情、先修缺口、来源、审核、别名、改名、合并、拆分、删除及操作审计。前端 `/mastery` 展示掌握度、置信度、遗忘风险、练习计数、来源摘录、先修缺口、身份治理和建议原因，并区分直接、间接、人工和 legacy 证据。

### 6.5 受控候选技术

| 技术 | 定位 | 当前结论 |
| --- | --- | --- |
| Qdrant | 资料 dense+sparse+RRF 对照实验 | 真实 Qdrant Local 已验证隔离、删除、重建和 sparse fallback；原生 RRF Recall@5 `0.95` 低于现有 hybrid 的 `0.9833`，轻量词项重排仅追平。**No-go**：不进入生产依赖。 |
| Neo4j | Optional Graph Backend；默认 Runtime 关闭 | Stage 6 保留默认 Runtime NO-GO 证据；Stage 7 已完成显式 selector、Projection dirty/rebuild lifecycle、初始化/caught-up readiness、`Neo4j -> SQL` fallback、稳定百分比/用户 canary rollout、Shadow 分离和真实 5.26 parity/stale-gate 验收。默认仍为 SQL；Knowledge/Learning Path V1 与 Explainable Multi-hop Association V1 已完成，长期灰度指标和真实数据 Benchmark 在后续阶段继续观察。 |
| Graphiti | 独立 Temporal/Episodic Vertical Slice；默认 Runtime 关闭 | Stage 6 已适配 `graphiti-core 0.30.1`；Stage 7 已完成 model-free reviewed temporal projection、current/as-of、supersede/invalidation、cross-user、delete/rebuild、SQL rehydrate 和 authenticated experimental API。固定零向量仅满足 Graphiti/Neo4j vector property 存储契约，外部 LLM/embedding/reranker 调用均为 0。60/300 declarations correctness `1.0`，但 p95 明显慢于 SQL，所以不替代 `MemoryDeclaration` / Temporal SQL Canonical，继续 default-off。 |
| LangGraph | `AgentRuntime` Spike 候选 | 必须通过持久化、SSE、确认式写入、恢复/取消、隔离、回放、降级和桌面分发验收 |
| LlamaIndex | 导入/文档处理编排 | 保留；不作为用户状态事实来源 |
| FSRS | 间隔复习调度 | 保留；回答“何时复习”，不回答“下一步学什么” |
| Cognee、Mem0 | 对照/设计参考 | 不作为核心依赖或事实来源 |
| LightRAG | 评估与策略参考 | 不进入运行时依赖 |
| Microsoft GraphRAG | 不适用 | 明确排除，不做 Spike |

## 7. 安全基线

1. 所有领域查询、详情、更新和删除都必须按 `current_user.id` 或可验证的用户归属过滤。
2. 上传目录访问必须要求认证，并确保解析后的路径位于允许的上传根目录内。
3. `.env`、数据库、真实上传内容、ChromaDB 数据、日志和真实密钥均不得提交。
4. AI Key 与搜索 Key 只可在后端配置/加密存储，不应存入浏览器持久化数据。
5. 资料、笔记、搜索结果、工具返回值应作为不可信内容包装，禁止其改变系统策略、工具权限或确认流程。
6. 公开部署前需设置随机 `SECRET_KEY`、关闭 `DEBUG`、收紧 `CORS_ORIGINS`，并补充速率限制、审计和恶意文件扫描策略。

## 8. 本地开发与交付

### 8.1 开发运行

```powershell
# 后端
cd backend
pip install -r requirements-dev.txt
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# 前端（另开终端）
cd frontend
npm install
npm run dev -- --host 0.0.0.0 --port 5173
```

Docker 场景使用根目录 `docker-compose.yml`。Windows 本地体验可使用根目录 `start.bat` 或 `start.ps1`。

### 8.2 数据库迁移

PostgreSQL 只允许通过 `python run_migrations.py` 管理 schema。迁移链由冻结的 v1.3 基线、Phase 1 增量、受控 Phase 2 迁移和默认关闭的 Mnemox V2 Stage 1～3 schema 组成：空库直接升级；经过严格表/列指纹校验的无版本 v1.3 库先写入基线版本再升级；其他无版本库会失败退出，要求先备份并人工对齐，避免错误 `stamp`。当前 head 为 `20260903_21`。该入口会用 PostgreSQL session advisory lock 串行化 schema 指纹识别、可能的 baseline stamp 和 Alembic upgrade，因此多副本启动时后续副本会等待当前迁移完成；不得以直接 `alembic upgrade` 绕过该入口。Docker 在启动 Uvicorn 前执行该入口。应用生命周期在 PostgreSQL 上只校验 Alembic head，绝不执行 `create_all`。Alembic 自动检查忽略 ORM 注释和 SQLite 本地 lightweight 账本，只比较结构、类型、约束和索引。

### 8.3 验证命令

```powershell
# 后端
cd backend
python -m pytest -q
python evaluate_retrieval.py --backend hybrid --min-recall-at-5 0.75 --summary-only
python evaluate_knowledge.py --min-explicit-recall-at-5 0.95 --summary-only

# 可选 Qdrant 复验，不属于生产依赖
pip install -r requirements-spike.txt
python evaluate_retrieval.py --backend all --include-qdrant --summary-only

# 前端
cd frontend
npm test
npm run build
npm run lint
# 先启动 Vite，并安装 Playwright Chromium
npm run test:e2e

# 桌面端
cd desktop
npm test
```

发布前还应执行 `git diff --check`，并验证版本号、发布清单和桌面安装包资产保持一致。

CI 还会在独立 PostgreSQL 16 服务库上执行空库迁移、`test_postgres_release_gate.py`、历史库 dump/restore/升级演练与 `alembic check`。历史门禁固定验证用户、资料、笔记、概念、事件、legacy learner evidence 和当前 schema；两个验收文件只有在对应环境变量明确指向 `postgresql+asyncpg` 时运行，普通 SQLite 单元套件会跳过它们。

## 9. 当前技术债与优化方向

| 优先级 | 事项 | 原因 |
| --- | --- | --- |
| P0 | 正式 PostgreSQL 发布升级 | 全新 PostgreSQL 16 已升级到 head `20260903_21`，通过 Stage 1～3 生命周期/隔离、extraction/projection `SKIP LOCKED`、多 worker、advisory lock 和 `alembic check`；旧迁移点的本地历史 dump/restore 到新 head 也已通过数据保留专项。远程候选 CI 与正式源库仍需在发布窗口完成冻结写入、真实快照、显式升级、生产数据/Vault/记忆/检索投影/AgentRuntime/Claim/run/resolution schema 核对与回滚准备。 |
| P0 | 真实关键路径 E2E | Chromium 草案取消/确认门禁与 Windows smoke 已在 GitHub CI 通过；仍需真实后端集成和 Windows Electron 启动/安装包 E2E。 |
| P0 | 多用户越权审计与回归测试 | 产品存在多领域详情、写入和文件访问接口，必须持续验证资源归属。 |
| P0 | 统一 Prompt Injection 防护 | RAG、笔记、搜索和工具返回均会进入模型上下文。 |
| P2 | RAG 状态前端回归 | 该能力已在 v1.2.0 主体落地，后续随检索迁移继续验证降级状态、最近错误和提示一致性。 |
| P1 | 拆分超大模块 | `learning`、`analytics`、Agent/Coach 相关实现的复杂度持续上升。 |
| P1 | 检索真实数据与笔记投影 | `RetrievalRouter`、资料 SQL/Chroma 投影、混合召回、更新/删除/重建及合成质量集已完成；后续扩大真实问题样本，并按需要补笔记独立 manifest。 |
| P1 | Claim 中心知识图谱 V2 | Stage 0～5 后端工程主链已收口；Stage 4 的真实人工牵强率/灰度与 Stage 5 的真实匿名中文/双语质量验收继续单列。Stage 6 默认 Runtime NO-GO 保留；Stage 7 Optional Neo4j Runtime、Knowledge/Learning Path V1、Explainable Multi-hop Association V1、Graphiti Temporal Slice、真实图数据库门禁、Compose optional profile 与 Architecture Story 均已工程收口。默认产品仍走 SQL；下一步通过云端 WebUI 导入真实技术笔记做中文/双语人评和长期灰度观测。 |
| P1 | 学习者模型真实校准 | 后端状态/证据、强弱信号、练习计数、FSRS、先修/目标/错误解释型推荐与前端下钻已完成；真实 holdout 数据不足，真实数据校准和生产排序监控待补。 |
| P1 | 事件投影与数据生命周期 | outbox 幂等、重试、分页回放、隔离、DLQ、常驻 worker、聚合指标和此前 PostgreSQL 16 CI 已通过；资料、概念来源和时态记忆派生均具备删除/失效清理，正式发布验收待补。 |
| P1 | 事务所有权统一 | 画像投影与 Agent 只读工具已改为服务层 flush-only、入口/checkpoint commit/rollback，失败画像刷新使用 savepoint，快照保持纯读；画像首次写入已用 PostgreSQL/SQLite 原子 upsert 消除主键竞争，并隔离字段所有权；服务/Agent 提交点已有所有权清单和 AST 双向门禁。资料/检索 saga 虽已显式登记，仍需按调用链逐项迁移并补失败注入，避免机械改动破坏独立 worker。 |
| P1 | 时间语义统一 | Agent/Coach、学习事件、记忆声明、画像、快照、检索投影与 outbox 已统一 naive UTC 数据库存储、偏移换算和 `Z` 边界；仍需盘点旧路由/服务，并为历史墙上时间报表制定带数据核对的迁移方案。 |
| P1 | 错误脱敏与诊断治理 | Agent、AI/RAG、检索投影、outbox/DLQ 和 worker 已统一秘密识别、幂等二次脱敏、单行限长、调用方错误码与安全关联指纹；历史数据库诊断已提供默认 dry-run、显式 apply、调用方事务与幂等批处理清理。仍需扩展 HTTP 领域错误码覆盖并制定集中日志、备份和导出的保留/访问策略。 |
| P1 | 时态记忆真实规模验证 | SQL 冲突、审核、纠错、到期失效、唯一约束与派生删除主链已完成；真实跨会话查询样本不足，只有出现明确缺口时才评估筛选 episode 与 Graphiti。 |
| P1 | Obsidian 同步一致性 | 稳定 Vault/文件身份、冲突候选、路径与文件安全保护、扫描失败保护和用户提示已完成；真实多 Vault 冲突/删除、并发幂等、watchdog 与写回仍待验收。 |
| P1 | 联想与 Coach 反馈闭环 | 显式联想已接入 Coach；行为闭环已能记录展示、开始、真实领域完成/中断与用户确认，并可回放。仍需积累真实样本、验证行为变化归因和保守阈值。 |
| P1 | 后台任务与可观测性 | opt-in 复习积压 worker 已具备逐用户计划、启动 catch-up、IANA 时区、本地日界线、免打扰延后、单用户硬超时、`SKIP LOCKED` 多实例防重复、完成/跳过/失败状态和有界重试；`/health` 暴露不含异常正文的运行计数。长耗时索引和跨场景统一预算/熔断仍需统一。 |
| P1 | AgentRuntime 产品化 | 原生单场景 worker、Agent 面板建议、周报草案，以及 Kernel 的预备任务、租约回收、受限上下文 checkpoint、用户确认精确续跑、SSE、取消、失败重试、预算护栏、供应商用量对账、规则 Planner fallback、用户隔离回放和幂等行动确认已接入；仍需比较原生 Kernel 与 LangGraph 的累计成本边界。 |
| P1 | 北极星指标事件链路 | 后端已有四项指标和 Coach A/A 观察报告；建议执行率区分领域事件与用户确认，实验报告区分成熟/归因中/未埋点曝光。Agent 页仅在 feature flag 开启时展示 A/A 分组且明确不改策略。真人覆盖、A/A 分组完整性和生产样本复核仍待完成。 |
| P1 | 知识巩固来源覆盖 | 周报已具备本地自然周、用户隔离、笔记/复习/错题来源版本、Obsidian 所有权和 copy-only 草案；仍需通过四层路由补资料证据、概念关系和时态记忆，并在真实规模下评估摘要长度。写回协议未定义前保持只读。 |
| P1 | 离线冲突处理 UI | 现有同步队列可重试，但服务端与本地并发修改的用户决策仍需完善。 |
| P2 | LLM 成本与数据生命周期 | AgentKernel 单次运行和逐用户 UTC 日已有调用次数与估算 Token 硬上限，并归一化三类 Provider 的真实 usage、按用户配置单价计算参考成本；日志/任务/投影的错误摘要已统一脱敏和限长，历史数据库诊断已有受控清理入口。仍需真实密钥/账单抽样核对，后台任务和概念抽取还需要跨场景预算、超时/熔断、外部日志保留期限和删除级联。 |

## 10. 演进方向与当前状态（2026-08-23 复核）

以下目标由 [2026-08-03 学习智能底座决策](superpowers/specs/2026-08-03-learning-intelligence-foundation-architecture.md) 定义。状态以代码和验收证据为准；“部分完成”不等于完成标准已满足。

| 方向 | 摘要 | 决策 | 阶段 |
| --- | --- | --- | --- |
| 规范数据与投影 | 关系型核心保留；补学习证据、概念状态、记忆声明、outbox 与检索投影 | 新 ADR §2/§4 | ✅ 学习证据、计数、outbox、时态记忆事实身份/唯一性/派生清理、资料 SQL chunk 与概念别名/来源/审计均已实现；正式发布仍单独验收 |
| 复习调度 | `py-fsrs` 替换手写 SM-2 风格调度 | 保留 | ✅ FSRS 优先 + SM-2 降级；版本化迁移、数据保留回归、离线 DDL 和一次性 PostgreSQL 16 演练完成 |
| 检索底座 | `RetrievalRouter` 统一检索；资料 SQL/Chroma 投影与受控选型 | 08-22 检索 ADR | ✅ 资料/笔记/概念/记忆/学习状态已统一；资料具备 ingest/refresh/forget/retry/rebuild、质量门禁和 Qdrant no-go，生产保留 Chroma + SQL keyword + RRF |
| 概念图谱 | 可审查的关系、证据和人工修正；Neo4j 已从 Stage 6 Shadow 进入 Stage 7 Optional Backend 建设 | 08-22 概念图谱 ADR + 2026-09-04 Stage 6/7 ADR | ✅ SQL Canonical 主链完整；Stage 7 Optional Runtime 已有 selector、projection lifecycle、readiness、fallback、rollout、真机 parity/stale gate、Knowledge/Learning Path V1 与 Explainable Multi-hop V1。Graphiti Temporal Slice 也已完成但保持独立 Experimental；下一缺口是 WebUI 真实笔记 dogfooding / 人评与长期灰度，而不是 backend 可运行性。 |
| 时态记忆 | SQL 记忆声明；Graphiti Spike 已结束 | 08-23 时态记忆 ADR + 2026-09-04 Stage 6 ADR | ✅ SQL 产品主链完整；Graphiti as-of/BM25 Shadow 正确性通过但性能/成本净收益失败，最终 NO-GO，Temporal SQL 保持权威 |
| 学习者模型 | 多源证据、状态、遗忘风险与下一步推荐 | 08-22 概念图谱 ADR | ✅ 强弱证据、答题/正确/提示计数、错题与 FSRS 回填、先修/目标/错误解释型推荐和前端下钻已完成；真实 holdout 校准仍待数据积累 |
| Obsidian 同步 | 先完成拉取式增量同步的稳定 ID、冲突/删除策略；watchdog 与写回后置 | 保留 | 🔶 稳定身份、冲突候选、安全输入边界和用户提示已完成；真实多 Vault 验收、watchdog 与写回未完成 |
| AgentRuntime | 原生 Kernel 与 LangGraph 的受控比较；草案确认、回放和 fallback 后再接调度 | 新 ADR §5/§6 | 🔶 受控原生切片已接前端调试入口、持久调度、租约回收、checkpoint 精确续跑、SSE、取消/重试/回放、预算护栏、供应商用量/配置单价对账和幂等草案确认；LangGraph 与真实账单抽样未完成 |
| 后台调度与自学习 | Coach 治理下的 catch-up、归因和确定性分桶 | 保留 | 🔶 单场景调度已具备 catch-up、时区/免打扰、硬超时、多实例跳锁和安全重试；默认关闭的 A/A 观察已接稳定分桶、不可变事件与成熟归因报告，仍需真人覆盖和独立 A/A 完整性验收，当前禁止策略差异与 bandit |
