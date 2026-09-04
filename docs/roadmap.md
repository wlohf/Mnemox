# Mnemox 路线图

> 状态：维护中
>
> 基线日期：2026-08-03
> 最近核查：2026-09-04
> 上游决策：[2026-08-03 学习智能底座架构决策](superpowers/specs/2026-08-03-learning-intelligence-foundation-architecture.md)

本文件是"接下来做什么、按什么顺序做"的唯一权威来源。需求范围见 [需求基线](requirements.md)，实现约定见 [技术基线](technical.md)，执行状态见 [进度文档](progress.md)。每个阶段收口时更新本文件与进度文档。

**状态口径**：`已交付` 表示代码已合入、迁移已验证、测试和验收证据齐全；`主体完成` 表示主要功能和验收已完成，但正式发布或少量收口动作尚未结束；`部分完成` 表示只有骨架、保底实现或后端子集；`实现中` 表示工作区已有原型但尚未接入主流程；`未开始` 表示尚无可用实现。降低验收范围时必须改写完成标准，不能只改状态。

## 0. 产品定位与原则

**定位**：Mnemox 不教用户学习方法——它把经过验证的学习科学（间隔效应、检索练习、行为设计、元认知）变成用户的默认行为。产品要解决的是"知道却做不到"的知行差距，而不是提供更聪明的答案。

五条执行原则：

1. **行为转化是北极星**：衡量一切功能的标准是四个行为指标（建议执行率、中断恢复时长、复习按时率、每周有效学习时段数），不是回答质量或功能数量。
2. **连接成熟软件，不与其竞争**：编辑器归 Obsidian，复习界面可归 Anki；Mnemox 只做别人做不了的——概念图谱、行为数据、教练策略。
3. **轮子优先但不盲目锁定**：调度用 FSRS、导入保留 LlamaIndex；Qdrant、Neo4j、Graphiti、LangGraph 先做有验收门槛的 Spike，未通过就保留现有基线，不为“完整感”引入不可运维依赖。
4. **规范来源优先**：SQLite/PostgreSQL、原始文件和事件账本是事实来源；向量库、图数据库、记忆图和 Agent checkpoint 都必须可重建、可删除、可迁移。
5. **降级纪律**：任何新层（图谱、记忆、联想、底座、Agent runtime）失败时不得破坏基础学习流程，延续现有 RAG 降级哲学。

## 1. 轨道总览

| 轨道 | 主题 | 前置 | 状态（2026-09-03 复核） |
| --- | --- | --- | --- |
| 立即（小胜利） | 自引激励收尾 + FSRS 调度替换 | 无 | 🔶 主体完成（FSRS 优先、SM-2 降级；笔记引用冷却与 Coach 反馈已接入；版本化迁移、离线验证和一次性 PostgreSQL 16 演练已完成；正式生产升级按发布窗口执行） |
| Phase 0 | Beta 稳定化 + 仓库卫生 | 无（与"立即"并行） | 🔶 主体收口中（授权/注入/RAG 可见化主体、主线整合和远程旧分支清理已完成；Chromium 草案确认、PostgreSQL 16 与 Windows smoke 已通过 GitHub CI；真实 Windows Electron E2E 待补） |
| Phase 1 | 四层学习智能底座：数据契约、事件投影、混合检索、概念图、时态记忆、学习者模型、Obsidian 与联想 | Phase 0 主体验收（数据边界允许并行收口） | 🔶 MVP 持续收口（统一检索、资料生命周期、SQL 概念审核/来源、可解释学习推荐、SQL 时态记忆与 Coach 教学行为闭环均已实现；PostgreSQL 备份、恢复和临时库升级已实演，正式源库升级与真实浏览器专项验收仍待发布窗口） |
| Phase 2 | AgentRuntime 垂直切片：原生 Kernel/LangGraph 对比、后台调度、自学习、知识巩固 | Phase 1 收口 | 🔶 已正式进入受控纵向切片：原生 Kernel 具备持久任务、恢复/取消、SSE、预算/用量对账和确认式行动；opt-in 调度已补齐 catch-up、时区、免打扰、超时和多实例跳锁；自学习 v0 已新增默认关闭的确定性 A/A 观察；知识巩固已接本地自然周扫描、稳定来源版本和 copy-only Markdown 草案。框架/真实账单抽样、远程 PostgreSQL 验收、真人样本、四层来源扩展和写回协议仍未完成 |
| Mnemox V2 | Claim 中心知识图谱：契约、SQL Claim、抽取、归一、Association V2、Sparse、Neo4j/Graphiti 条件 Shadow | Stage 0～3 已验收；Stage 4 进入受控实现 | 🔶 Stage 4 后端纵向切片已落地：ClaimRelation、GraphStore/SqlGraphStore、`/api/knowledge/associate`、feature flag 回滚、确定性 Feature Ranker 与离线 V1/V2 对照均已接入；合成集显式 Recall@5 保持 `1.0`、隐式从 `0.0` 提升到 `1.0`，隔离/删除残留/无证据展示/负例误关联均为 `0`。真实人工牵强率、真实语料与产品灰度尚未验收，因此不标记 Stage 4 完成，Association V1 仍保留主线回滚。 |
| Phase 3 | 生态：MCP server、语音、AnkiConnect、一键 Demo | Phase 2 | 未开始 |

## 2. 立即（小胜利轨道）

目标：短周期内交付两个"符合初心、成本小、感知强"的改进。

| 事项 | 内容 | 完成标准 |
| --- | --- | --- |
| 自引激励收尾 | 现有 `motivation_service` 笔记引用能力接入 `low_motivation` / `frustration_support` / `restart_after_interruption` 等 Coach 技能；增加摘录引用防疲劳（同摘录冷却）；接入采纳反馈 | 低动力场景下能引用用户自己的笔记原文并注明出处；同一摘录不在冷却期内重复出现；用户反馈落库；测试证据已保留 |
| FSRS 替换 | 用 `py-fsrs` 替换手写 SM-2 风格调度，保留 SM-2 降级和 legacy 字段；两段 Alembic 迁移已实现 | 新复习间隔由 FSRS 计算；存量卡不丢失复习历史；SQLite/单元数据保留回归、PostgreSQL 离线 DDL 和一次性 PostgreSQL 16 升级演练已完成；正式生产升级按发布窗口执行 |

## 3. Phase 0：Beta 稳定化（不动摇）

沿用需求基线 P0，另加仓库卫生：

| 事项 | 完成标准 |
| --- | --- |
| 多用户授权审计 | 所有详情/更新/删除/文件接口绑定 `current_user.id` 并有回归测试 |
| Prompt Injection 统一防护 | 资料、笔记、搜索、工具输出统一不可信上下文边界，含恶意样例测试 |
| RAG 状态可见化 | 资料侧栏和设置入口展示语义检索/关键词回退/最近错误；聊天等入口状态语义一致，并有浏览器 E2E 验证 |
| 关键路径集成验证 | API 冒烟覆盖登录、上传、对话、计划、笔记、复习和 Agent 草案生成；Chromium 门禁已在 GitHub CI 覆盖番茄钟、计划、笔记、侧栏跳转及 Agent 草案取消无副作用/确认后执行；真实 Windows Electron E2E 仍需另行验收 |
| 仓库卫生 | 已清理被基线替代的历史文档，完成 Phase 1 主线整合、旧分支归档和跨平台换行规则；发布清单仍需在下一版本发布窗口单独核对 |

2026-08-13 和 2026-08-19 的主线整合分别收敛既有功能与 ContextStore、Coach、Vault、记忆声明增量。2026-08-22 PR #8 将 `RetrievalRouter` 资料主链合入 `main@5da524c`；[CI run 32559668354](https://github.com/wlohf/Mnemox/actions/runs/32559668354) 的 Backend、Frontend、PostgreSQL 16、Chromium、Windows smoke 和 Repository integrity 六项均已通过。这些合并不创建新版本 tag 或安装包；真实 Electron E2E 与正式生产升级仍单独验收。Phase 2 仍必须等待 Phase 1 数据、删除、重放和反馈边界收口。

## 4. Phase 1：四层学习智能底座

目标：先让资料、关系、用户记忆和学习能力各自有清晰的数据边界，再让功能模块通过稳定接口组合。目标架构见 [2026-08-03 决策](superpowers/specs/2026-08-03-learning-intelligence-foundation-architecture.md)。

| # | 事项 | 完成标准 | 状态 |
| --- | --- | --- | --- |
| 1 | 规范数据契约 | 新增/演进 `learner_evidence`、`user_concept_state`、记忆声明、`projection_outbox` 与检索投影；定义稳定 ID、版本、删除和重建语义 | ✅ 学习证据、计数、记忆事实身份/唯一约束/冲突关系、outbox、资料投影与概念别名/来源/审计均具备版本化 SQL 迁移、用户隔离和派生删除语义 |
| 2 | 事件与投影 | 领域数据与 `LearningEvent` 同事务；服务层不得私自提交调用方 unit of work；投影任务具备幂等、重试、状态、重放和按用户删除；至少一个真实投影流完成回放 | 🔶 outbox 幂等、DLQ、分页回放、跨实例心跳与 PostgreSQL 16 多 worker CI 已通过；资料投影已补 `ingest/refresh/forget/rebuild/retry`、配置失效和失败删除墓碑，投影身份使用 PostgreSQL/SQLite 原子冲突处理；用户长操作持全局配置共享锁和同用户 fencing，配置保存/热重载/失效标记持排他锁，二者不会交错；画像投影和 Agent 只读工具已改为 flush-only、调用方提交，画像刷新用 savepoint 隔离失败，学习快照保持纯读，画像首次写入使用 PostgreSQL/SQLite 原子 upsert 并限制冲突更新字段；服务/Agent 的剩余提交点已有所有权理由清单和 AST 双向门禁；Agent/Coach/事件/记忆/画像/outbox 主链已统一 naive UTC 入库与 RFC 3339 `Z` 边界，显式用户时区继续负责自然日/周；Agent、RAG、检索投影、outbox/DLQ 和 worker 失败已统一幂等脱敏、稳定错误码与安全关联指纹，历史数据库诊断已有 dry-run/显式 apply/可回滚幂等清理；历史墙上时间统计、HTTP 错误码覆盖及外部日志保留治理仍需逐步迁移，正式生产升级待发布窗口 |
| 3 | 统一检索与资料生命周期 | `RetrievalRouter` 收敛资料/笔记/记忆/概念/学习状态；资料投影具备版本、删除、重建、关键词降级、用户隔离和离线质量门禁 | ✅ 主链完成：主聊天、ChatAgent、AgentKernel 与资料搜索使用统一 Router；SQL chunk + Chroma 投影、资料更新、删除恢复、前端状态及 16-case 质量集已接入 |
| 4 | Qdrant 检索 Spike | 对同一资料集比较 dense+sparse/BM25+rerank 与现有基线；通过 Windows 打包、无 embedding 降级、删除/重建、延迟和成本门槛后再决定是否采纳 | ✅ 已完成受控 go/no-go：Qdrant Local 真机对比未证明明显质量优势，轻量词项重排只追平 Recall@5；保留 Chroma，Qdrant 不进入运行时依赖 |
| 5 | 概念图谱 MVP 与 GraphStore Spike | 三表、上传抽取、错题回填、人工改名/合并/删除、来源和质量集完成；只有 SQL 不足时才评估 Neo4j，Spike 不通过不影响 SQL 图 | ✅ SQL 主链已完成：资料自动候选/别名/先修关系、审核、来源版本、更新/删除清理、改名/合并/拆分/删除、错题回填、跨用户/环路拦截和先修缺口均有专项回归；SQL 能满足当前规模，Neo4j 不引入 |
| 6 | 时态记忆与 Graphiti Spike | `UserMemory` 演进为可审核记忆声明；仅投影筛选后的状态变化 episode；验证失效/冲突/纠错/删除和 SQL 重建 | ✅ SQL 产品主链完成：事实键、部分唯一约束、历史重复回填、跨来源冲突、审核前旧事实保留、确认替代、拒绝/纠错、自动失效、全入口过滤、派生画像删除和前端对照审核均有回归；当前 SQL 满足需求，Graphiti 不引入运行时 |
| 7 | 学习者模型 | 直接证据主导、间接信号只校准风险/置信度；一次练习或复习可更新概念状态，前端展示证据、模型版本和人工修正 | ✅ 产品主链已完成：强弱证据、练习/正确/提示计数、错题与 FSRS 回填、先修/目标/风险/错误解释型排序及前端原因下钻；真实 holdout 校准继续保持 `collect_more_data`，不冒充已完成 |
| 8 | Obsidian、联想与体验 | 拉取式同步稳定 ID/冲突/删除；联想接入 Coach 的 shown/feedback/采纳事件；概念地图、先修缺口和建议理由可下钻 | 🔶 Vault 安全、联想 Coach 归因、概念详情、先修缺口、来源证据和建议理由均已接入；Coach 的展示→行动尝试→真实番茄钟/复习/计划确认或用户确认→回放已通过本地专项验证，仍待 PostgreSQL 与真实浏览器专项验收；真实 Vault 冲突/删除仍待验收 |

当前执行检查点（不得跳步）：

1. **当前收口：Coach 教学行为闭环验收**。SQLite 中的观察、策略、低阻力行动、草案确认及 shown/accepted/rejected/started/completed/abandoned 归因已回归；确认回放、过期、降级与指标定义在 PostgreSQL 和真实浏览器路径一致。
2. 验收通过后再评估 AgentRuntime；Graphiti 只在 SQL 时态查询与已筛选 episode 出现真实能力缺口时启动受控 Spike。
3. 检索生产基线固定为 `RetrievalRouter → Chroma + SQL keyword + RRF`；继续扩大真实问题与资料样本，不因小型合成评测就采用 Qdrant。
4. 真实学习证据达到至少 50 个 holdout case 后再运行学习者模型离线校准；门槛不足时保持 `collect_more_data`，不阻塞当前功能地基开发。
5. Obsidian 真实 Vault 冲突 / 删除、正式 PostgreSQL 升级和真实 Windows Electron 启动 / 安装 E2E 属于后续专项验收，不与已通过的 CI smoke 混淆。
6. 图谱、学习状态、时态记忆和 Coach 闭环完成后，才比较原生 AgentRuntime 与 LangGraph；不提前启动多 Agent、语音或 MCP。

检索生命周期、质量集、实测数据和 Qdrant go/no-go 详见 [2026-08-22 检索生命周期与质量决策](superpowers/specs/2026-08-22-retrieval-lifecycle-quality-adr.md)。
概念审核、来源生命周期、身份迁移、可解释排序及 SQL 图谱选型详见 [2026-08-22 概念图谱与学习推荐决策](superpowers/specs/2026-08-22-concept-graph-learning-recommendations-adr.md)。
时态事实身份、唯一约束、冲突审核、自动失效、派生删除和 Graphiti 暂缓详见 [2026-08-23 SQL 时态记忆生命周期决策](superpowers/specs/2026-08-23-temporal-memory-lifecycle-adr.md)。

阶段验收：规范数据可重放并重建全部投影；至少一个真实业务流完成 `ContextStore` 迁移；候选检索/图/时态记忆技术有可复现的 go/no-go 证据；上传资料后概念关系可人工修正；一次练习/复习能更新 `user_concept_state` 并展示理由；联想有 Coach 的 shown/accepted/completed 基线；删除和用户隔离有回归测试。拉取式同步达到上述标准即可，不把 watchdog 误标为已完成。

## 5. Phase 2：AgentRuntime 升级

目标：Agent 在四层底座之上提供可恢复、可审计的工作流；“不在场时也在观察、判断、择机介入”必须后置于数据闭环和 Coach 治理，不等于开放式自主写入。

| # | 事项 | 完成标准 |
| --- | --- | --- |
| 1 | AgentRuntime Spike | 用“复习积压”场景比较原生 AgentKernel 与 LangGraph；原生路径现已具备持久任务、短租约、过期回收、受限上下文 checkpoint、用户确认的下一步精确续跑、SSE 实时订阅与断线回放、用户隔离、协作取消、预算护栏、供应商真实 Token/配置单价参考成本对账和幂等行动确认，仍需 PostgreSQL 候选验收、真实密钥账单抽样核对和桌面分发对照；未证明 LangGraph 有净收益则继续原生 Kernel |
| 2 | AgentKernel 单一纵向闭环 | 多步只读工具调用、调试前端入口、租约过期回收、checkpoint 精确续跑、持久日志 SSE 和确认式行动草案已接入，任务在首个模型调用前持久化，写入只接受服务端凭据并重新验证用户/目标；模型调用次数与估算 Token 的单次/逐用户日上限会在下一次调用前硬停止，调用后归一化 OpenAI-compatible、Claude 和 Gemini usage，按用户配置单价计算参考成本，并把未取得 usage 的调用单独计数。Provider/模型/预算失败会显式生成规则简报，原任务继续保留失败状态与 checkpoint，降级行动仍走服务端确认凭据。同一用户运行通过 PostgreSQL 用户行锁串行化。继续补真实账单抽样核对；运行时选型未收口前不能替代旧 Planner |
| 3 | 后台调度器 MVP | “复习积压”已按 opt-in 用户持久化计划和幂等运行键；代码与本地回归已覆盖启动 catch-up、IANA 时区、本地日界线、跨午夜免打扰延后、单用户硬超时、完成/跳过/失败状态、有界指数退避和 `SKIP LOCKED` 多实例防重复；远程 PostgreSQL 16 双 worker 验收待候选 workflow，所有触达仍经 Coach 治理 |
| 4 | 干预效果自学习 v0 | 默认关闭的 feature flag 已接确定性用户级 A/A 分桶；实验元数据随不可变 Coach 生命周期事件保存，用户级报告按 7 天成熟窗统计接受、开始、完成、真实领域完成、放弃和拒绝，并报告未埋点覆盖。两组策略完全相同、决策就绪度固定为 false；只有积累真人覆盖、通过 A/A 完整性校验并新增独立决策后才允许 A/B，当前禁止 bandit 和自动调参 |
| 5 | 知识巩固与周报 | 第一条只读切片已按 IANA 时区扫描本地自然周，聚合用户自有的笔记、已完成复习和错题线索；来源带内容版本指纹、稳定草案键、页面路由及 Mnemox/Obsidian 只读/冲突所有权，vault `missing` 来源不进入草案。Agent 页只展示有限摘录并复制 Markdown，不创建笔记、不隐式更新画像、不回写 Obsidian。下一步通过四层路由补资料、概念和时态记忆证据；只有另立写回协议、冲突与回滚验收后才讨论写回，夜间任务仍须可取消、可重试、可观测 |

阶段验收：一次典型干预可完整回放"为何触发、依据什么、展示给谁、用户是否接受/执行、后续行为变化"；失败、取消、重试和降级也有状态记录。只有该证据和灰度指标齐全才算 Phase 2 完成。

## 6. Mnemox V2：Claim 中心知识图谱

目标与完整阶段门禁见 [Mnemox V2 Claim 中心知识图谱实施设计](superpowers/specs/2026-09-02-mnemox-v2-claim-centered-knowledge-graph-implementation.md)。本轨道继续以 SQLite/PostgreSQL 为规范来源，第一版关系查询固定为 `SqlGraphStore`；Chroma、Sparse、Neo4j 和 Graphiti 都只能是可重建投影或 Shadow 候选。

### 6.1 与当前 Phase 2 的执行窗口

1. Stage 0 只增加文档、合成 fixture、离线 runner 和默认关闭配置，不触碰生产数据与请求路径，因此允许在当前 Phase 2 收口期间完成。
2. 2026-09-02 产品负责人明确授权 Stage 1 先行，完成默认关闭的 Canonical Claim Schema、来源生命周期和双数据库门禁。
3. 2026-09-03 产品负责人明确授权并依次验收 Stage 2～3：先完成统一 Extraction Schema、确定性/LLM 抽取、Evidence Grounding 和可恢复 run，再完成 Entity Resolution、知识 embedding 投影、人工审核与投影恢复；没有借此启动 Association V2 或外部图运行时。
4. Stage 3 完成并验收后才进入 Stage 4；Stage 4 通过前，Association V2 不成为产品数据主线，V1 始终保留 feature flag 回滚。
5. Stage 5 只能基于 Stage 4 的真实规模数据优化 Sparse/Reranker；Stage 6 用于 Neo4j/Graphiti Shadow 与 Go/No-Go。Stage 6 的 Runtime No-Go 不等于放弃图架构：按 [图基础设施提前建设策略](superpowers/specs/2026-09-04-mnemox-v2-graph-foundation-strategy.md) 保持 Architecture READY。
6. Stage 0～6 工程/Spike 已完成；Stage 4/5 的真实人工牵强率、匿名语料与产品灰度继续作为质量验收后置。2026-09-04 追加“产品 + 技术学习 / 作品集”双目标后，新增 [图架构演进、技术选型与作品集目标决策](superpowers/specs/2026-09-04-mnemox-v2-graph-evolution-and-portfolio-architecture.md)：Neo4j 重新打开为 Optional Graph Backend 建设目标，Graphiti 重新打开为独立 Temporal/Episodic Vertical Slice；默认产品 Runtime 仍不强制依赖二者。

### 6.2 阶段状态

| Stage | 范围 | 前置与退出门禁 | 状态 |
| --- | --- | --- | --- |
| 0 | 契约、评测、关闭开关 | ≥50 联想问题、≥50 Claim/Evidence Unit；无敏感数据；V1 baseline 可重复且零外部模型调用；路线图明确窗口 | ✅ 已完成：56 个问题、50 个标注 Unit；显式 Recall@5/MRR `1.0`，隐式均为 `0.0`；隔离/删除残留 `0`；九个开关默认关闭 |
| 1 | Canonical Claim Schema | Stage 0 验收；SQLite 新旧库和 PostgreSQL 迁移、隔离、版本与删除门禁；不接自动抽取或 Association V2 | ✅ 已完成：Source/Revision/Unit/Claim/Evidence 五表、迁移 `20260902_19`、Material/Note 生命周期和手工 Grounding 已通过 SQLite 与全新 PostgreSQL 16 验收 |
| 2 | 统一抽取与 Grounding | Stage 1；Evidence 覆盖 100%，无定位 Claim 写入为 0，自动结果 pending，可恢复/降级 | ✅ 已完成：严格共享 Schema、确定性/LLM extractor、精确/归一 Grounding、pending Claim、迁移 `20260903_20` 与可租约/重试/取消/partial 的 durable run 已通过 SQLite 和全新 PostgreSQL 16 验收 |
| 3 | Entity Resolution 与 Knowledge Embedding | Stage 2；exact/alias、Top-5、零自动语义合并、隔离/删除/重建门禁 | ✅ 已完成：迁移 `20260903_21`、exact/alias/人工复用 resolver、pending 语义候选、ClaimConceptLink、四类知识投影、compact outbox、审核抽屉和双数据库门禁均通过；记录式合成 Top-5 Recall `1.0`、跨用户/自动语义合并/删除重建残留 `0` |
| 4 | Association V2 + SqlGraphStore | Stage 3；隐式 Recall@5 相比 V1 提升 ≥20 个百分点，无证据展示 0，V1/V2 可切换 | 🔶 后端纵向切片已完成并通过合成门禁：显式 `1.0 → 1.0`、隐式 `0.0 → 1.0`，跨用户/删除残留/无证据展示/负例误关联均为 `0`；Judge 故障会回退 confirmed graph path。尚缺真实人工标注的牵强/不支持关联率 ≤5%、真实语料与产品灰度验收，因此暂不标记 Stage 4 完成。 |
| 5 | Sparse 规模化与 Reranker | Stage 4；质量不退化，目标规模 p95/内存改善，reference fallback 可用 | ✅ **工程阶段已收口，真实质量验收单列后置**：`SparseKnowledgeIndex` 默认 `auto`，SQLite→FTS5、PostgreSQL→原生 GIN FTS，查询异常回退 reference；claim-level dirty + `sparse_knowledge` outbox、target 隔离和 savepoint 失败保护均已接入。5,000 Claim SQLite p95 `423.94ms → 10.58ms`（约 `40.07x`），PostgreSQL 16 `407.20ms → 29.03ms`（约 `14.03x`），parity 均为 true；可选 LLM reranker 复用用户 Provider，并记录模型/延迟/token/配置成本，异常或超时退回 Feature Ranker。真实匿名中文/双语语料与真人牵强率仍未验收，不把工程收口误写成产品质量验收完成。 |
| 6 | Neo4j / Graphiti Shadow Spike | Stage 5；分别验证图查询投影与时态关系层，只记录脱敏差异，不改变用户结果，完成完整 go/no-go | ✅ **已完成，双 NO-GO**：Neo4j 在 1000/5000 Claim 合成图上 ID/path/score 一致率均 `1.0`、隔离/正文泄漏为 0；5000 combined p95 `33.97ms → 19.20ms`，但 direct 无稳定收益，且测试容器约 `0.7–1.0 GiB` 内存 / `~0.52 GiB` 数据盘，新增常驻服务/备份/凭据/桌面双后端成本，净收益门槛失败。Graphiti 0.30.1 已通过合法 group_id、as-of temporal search、来源版本失效、故障隔离和真实 Neo4j BM25-only 集成；100/1000 facts Recall@5 均与 SQL 为 `1.0`，但 p95 分别 `14.24/19.15ms`，慢于 SQL `8.28/9.62ms`，且正常 ingestion 还需 embedding/LLM。详见 2026-09-04 最终 ADR。 |
| 7 | Optional Graph Backend + Graph-native Feature + Temporal Slice | 在 Stage 6 安全/正确性证据上，把 Neo4j 做成可选 Graph Backend，并实现 Knowledge/Learning Path、Explainable Multi-hop；Graphiti 做独立 Temporal/Episodic Vertical Slice。SQL Canonical、desktop fallback、Shadow、Rebuild、灰度与回滚继续保留 | ✅ **工程阶段已收口，默认仍为 SQL**：Graph Domain、Optional Neo4j selector/readiness/fallback/rollout、Knowledge/Learning Path V1、Explainable Multi-hop Association V1、Graphiti Temporal Slice、Compose optional profile、真实 Neo4j/Graphiti integration、前后端回归和 Architecture Story 均已完成。最终宽回归 `149 passed`，真实 Neo4j/Graphiti 图数据库专项另有 `6 passed`，前端 `27 files / 93 tests` + build/lint 通过。Graphiti benchmark correctness 为 `1.0` 但明显慢于 SQL，因此保持 Experimental/default-off。真实中文/双语人评不伪装成工程验收，下一阶段通过云端 WebUI 导入用户自己的技术笔记做 dogfooding。 |

### 6.3 上线前 2～4 周图架构深化

当前没有强制上线 deadline，因此将剩余窗口用于“做深而不是做多”。权威实施计划：

`docs/superpowers/plans/2026-09-04-mnemox-v2-neo4j-graphiti-implementation-plan.md`

执行优先级：

- [x] **P0 图领域模型**：已冻结 Node / Edge / Relation type / 方向 / Evidence / 生命周期语义；见 `2026-09-04-mnemox-v2-graph-domain-contract.md`。
- [x] **P1 GraphStore 契约**：storage-neutral path DTO、显式 traversal direction、`find_concept_paths(...)` 能力边界和 `GRAPH_BACKEND=sql|neo4j` selector 已完成；SQL 通用 path 明确 unsupported，不为 parity 自研通用图引擎。
- [x] **P2 Neo4j 可选运行时地基**：Projection dirty propagation、rebuild-only two-slot coalescing、同用户跨进程串行、初始化/caught-up/Lag/DLQ readiness、request-scoped fallback、稳定百分比/用户 canary 灰度、Shadow 保留与真实 Neo4j parity 已收口；默认仍为 SQL，真实长期灰度指标继续在上线阶段观察。
- [x] **P3 Graph-native 产品能力**：Knowledge / Learning Path V1 与 Explainable Multi-hop Association V1 均已完成；
- [ ] **P4 真实数据与 Benchmark**：工程 benchmark 已覆盖 Neo4j 与 Graphiti correctness/p50/p95/rebuild/fallback；中文/英文/双语真实笔记的人评移到 WebUI dogfooding，仍保持未完成状态；
- [x] **P5 Graphiti Temporal Slice**：reviewed `MemoryDeclaration` → model-free Graphiti temporal projection → current/as-of/invalidation → SQL rehydrate 已完成，并通过真实 Graphiti + Neo4j 集成与 60/300 declarations benchmark；
- [ ] **P6 可选一个 Graph Analytics**：bridge concept / community / central concept 三选一，有产品入口才做；
- [x] **P7 上线与面试材料工程收口**：默认/graph Compose 边界、真实 integration、Architecture Story、ADR、Benchmark 与回滚 checkpoint 均已完成；可演示的真实笔记 WebUI dogfooding 作为紧接 Stage 7 的产品验证入口继续建设。

如果时间不足，宁可不做 Graph Analytics，也必须把 **Optional Neo4j Backend + Knowledge Path + Graphiti Temporal Slice + Benchmark** 做完整。

Stage 0 与 Stage 3 的离线入口：

```bash
cd backend
venv/bin/python evaluate_knowledge.py --min-explicit-recall-at-5 0.95 --summary-only
venv/bin/python evaluate_entity_resolution.py --summary-only
```

合成 baseline 和记录式 embedding 排名固定的是回归契约，不等同真实 provider 或真实用户验收。Stage 1 来自 2026-09-02 的明确授权，Stage 2～3 来自 2026-09-03 的连续明确授权；Stage 3 授权不自动延伸到 Stage 4、Association V2 或图后端运行时。

## 7. Phase 3：生态

| 事项 | 说明 |
| --- | --- |
| MCP Server | 暴露画像/图谱/错题/复习状态给外部 AI 客户端 |
| 语音 | TTS 朗读激励与提醒 → 按住说话 STT → 全双工对话（依次评估） |
| AnkiConnect | 评估用真 Anki 承载复习界面 |
| 一键 Demo | 示例数据 + 快速体验（沿用需求基线 P2） |
| 发布自动化 | 版本、构建、Release 资产、清单自动化 |

## 8. 冻结清单（默认不做）

- Markdown 编辑器新功能（保留现状供独立使用）。
- 新增业务页面（除非能回答"降低了哪个行为的执行阻力"）。
- 任何站点音视频下载功能（合规替代：本地音频导入 + B 站官方 iframe 嵌入）。
- 多人共学（沿用需求基线 P2 前置条件：先完成权限、隐私与授权设计）。
- 在 AgentRuntime Spike 未通过前，不锁定通用 agent 框架；`earendil-works/pi` 继续不引入，LangGraph 只作为受控候选，不得绕过 Mnemox 的权限、Coach 和草案确认。
- Microsoft GraphRAG 不纳入运行时或离线索引；LightRAG 只作评估与参考，不进入依赖树。
- 不把 Cognee、Mem0、Graphiti、Qdrant 或 Neo4j 作为用户事实、掌握度或权限的唯一来源。
- 在没有数据迁移、归因链路和回滚开关前，不引入 bandit 或其他在线策略学习。
- Mnemox V2 Stage 4 的真实人工质量验收继续单列；Stage 6 已于 2026-09-04 双 NO-GO，因此不引入 Neo4j/Graphiti 默认运行时、产品切流或桌面服务，除非未来满足重评 ADR 的新证据触发条件。

## 9. 维护约定

- 每个阶段收口：更新本文件状态、`progress.md` 快照，并在 `docs/updates/` 记录周期变更。
- 顺序原则：一条线收口再开下一条；跨阶段并行仅限"立即轨道 + Phase 0"。
- 决策变更（如 Spike 结论、框架取舍）必须新增或修订 `docs/superpowers/specs/` 决策文档，不允许只改代码不改文档；每次候选技术通过或否决都要保留可复现证据。
- 每个事项必须同时维护目标指标、范围/非目标、依赖、迁移、失败降级、测试证据、观测、灰度和回滚信息；代码存在不等于事项完成。
