# Mnemox 路线图

> 状态：维护中
>
> 基线日期：2026-08-03
> 最近核查：2026-08-22
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

| 轨道 | 主题 | 前置 | 状态（2026-08-22 复核） |
| --- | --- | --- | --- |
| 立即（小胜利） | 自引激励收尾 + FSRS 调度替换 | 无 | 🔶 主体完成（FSRS 优先、SM-2 降级；笔记引用冷却与 Coach 反馈已接入；版本化迁移、离线验证和一次性 PostgreSQL 16 演练已完成；正式生产升级按发布窗口执行） |
| Phase 0 | Beta 稳定化 + 仓库卫生 | 无（与"立即"并行） | 🔶 主体收口中（授权/注入/RAG 可见化主体、主线整合和远程旧分支清理已完成；Chromium 草案确认、PostgreSQL 16 与 Windows smoke 已通过 GitHub CI；真实 Windows Electron E2E 待补） |
| Phase 1 | 四层学习智能底座：数据契约、事件投影、混合检索、概念图、时态记忆、学习者模型、Obsidian 与联想 | Phase 0 主体验收（数据边界允许并行收口） | 🔶 MVP 持续收口（统一检索、资料生命周期、SQL 概念审核/编辑/来源、先修缺口与可解释学习推荐已完成；下一完整模块为 SQL 时态记忆冲突、替代、失效与纠错） |
| Phase 2 | AgentRuntime 垂直切片：原生 Kernel/LangGraph 对比、后台调度、自学习、知识巩固 | Phase 1 收口 | 🔶 AgentKernel 原型实现中；运行时 Spike、调度、自学习归因、知识巩固与写回未开始 |
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
| 1 | 规范数据契约 | 新增/演进 `learner_evidence`、`user_concept_state`、记忆声明、`projection_outbox` 与检索投影；定义稳定 ID、版本、删除和重建语义 | 🔶 学习证据、计数、记忆声明、outbox、资料投影与概念别名/来源/审计已具备版本化 SQL 迁移；时态记忆冲突与派生失效仍待闭环 |
| 2 | 事件与投影 | 领域数据与 `LearningEvent` 同事务；投影任务具备幂等、重试、状态、重放和按用户删除；至少一个真实投影流完成回放 | 🔶 outbox 幂等、DLQ、分页回放、跨实例心跳与 PostgreSQL 16 多 worker CI 已通过；资料投影已补 `ingest/refresh/forget/rebuild/retry`、配置失效和失败删除墓碑；正式生产升级待发布窗口 |
| 3 | 统一检索与资料生命周期 | `RetrievalRouter` 收敛资料/笔记/记忆/概念/学习状态；资料投影具备版本、删除、重建、关键词降级、用户隔离和离线质量门禁 | ✅ 主链完成：主聊天、ChatAgent、AgentKernel 与资料搜索使用统一 Router；SQL chunk + Chroma 投影、资料更新、删除恢复、前端状态及 16-case 质量集已接入 |
| 4 | Qdrant 检索 Spike | 对同一资料集比较 dense+sparse/BM25+rerank 与现有基线；通过 Windows 打包、无 embedding 降级、删除/重建、延迟和成本门槛后再决定是否采纳 | ✅ 已完成受控 go/no-go：Qdrant Local 真机对比未证明明显质量优势，轻量词项重排只追平 Recall@5；保留 Chroma，Qdrant 不进入运行时依赖 |
| 5 | 概念图谱 MVP 与 GraphStore Spike | 三表、上传抽取、错题回填、人工改名/合并/删除、来源和质量集完成；只有 SQL 不足时才评估 Neo4j，Spike 不通过不影响 SQL 图 | ✅ SQL 主链已完成：资料自动候选/别名/先修关系、审核、来源版本、更新/删除清理、改名/合并/拆分/删除、错题回填、跨用户/环路拦截和先修缺口均有专项回归；SQL 能满足当前规模，Neo4j 不引入 |
| 6 | 时态记忆与 Graphiti Spike | `UserMemory` 演进为可审核记忆声明；仅投影筛选后的状态变化 episode；验证失效/冲突/纠错/删除和 SQL 重建 | 🔶 SQL 声明基础已完成：人工和自动来源均保留来源、版本、审核、替代和删除语义；Graphiti Spike 未开始 |
| 7 | 学习者模型 | 直接证据主导、间接信号只校准风险/置信度；一次练习或复习可更新概念状态，前端展示证据、模型版本和人工修正 | ✅ 产品主链已完成：强弱证据、练习/正确/提示计数、错题与 FSRS 回填、先修/目标/风险/错误解释型排序及前端原因下钻；真实 holdout 校准继续保持 `collect_more_data`，不冒充已完成 |
| 8 | Obsidian、联想与体验 | 拉取式同步稳定 ID/冲突/删除；联想接入 Coach 的 shown/feedback/采纳事件；概念地图、先修缺口和建议理由可下钻 | 🔶 Vault 安全、联想 Coach 归因、概念详情、先修缺口、来源证据和建议理由均已接入；真实 Vault 冲突/删除与 Coach 完整教学反馈仍待专项验收 |

当前执行检查点（不得跳步）：

1. **下一完整模块：SQL 时态记忆闭环**。完成同一事实的冲突检测、替代、生效/失效、用户纠错、待确认信息及删除后的派生清理；SQL 仍是唯一规范事实来源。
2. 随后完成 Coach 教学行为的观察、策略、低阻力行动、草案确认及 shown/accepted/rejected/started/completed/abandoned 反馈归因，再评估 AgentRuntime。
3. 检索生产基线固定为 `RetrievalRouter → Chroma + SQL keyword + RRF`；继续扩大真实问题与资料样本，不因小型合成评测就采用 Qdrant。
4. 真实学习证据达到至少 50 个 holdout case 后再运行学习者模型离线校准；门槛不足时保持 `collect_more_data`，不阻塞当前功能地基开发。
5. Obsidian 真实 Vault 冲突 / 删除、正式 PostgreSQL 升级和真实 Windows Electron 启动 / 安装 E2E 属于后续专项验收，不与已通过的 CI smoke 混淆。
6. 图谱、学习状态、时态记忆和 Coach 闭环完成后，才比较原生 AgentRuntime 与 LangGraph；不提前启动多 Agent、语音或 MCP。

检索生命周期、质量集、实测数据和 Qdrant go/no-go 详见 [2026-08-22 检索生命周期与质量决策](superpowers/specs/2026-08-22-retrieval-lifecycle-quality-adr.md)。
概念审核、来源生命周期、身份迁移、可解释排序及 SQL 图谱选型详见 [2026-08-22 概念图谱与学习推荐决策](superpowers/specs/2026-08-22-concept-graph-learning-recommendations-adr.md)。

阶段验收：规范数据可重放并重建全部投影；至少一个真实业务流完成 `ContextStore` 迁移；候选检索/图/时态记忆技术有可复现的 go/no-go 证据；上传资料后概念关系可人工修正；一次练习/复习能更新 `user_concept_state` 并展示理由；联想有 Coach 的 shown/accepted/completed 基线；删除和用户隔离有回归测试。拉取式同步达到上述标准即可，不把 watchdog 误标为已完成。

## 5. Phase 2：AgentRuntime 升级

目标：Agent 在四层底座之上提供可恢复、可审计的工作流；“不在场时也在观察、判断、择机介入”必须后置于数据闭环和 Coach 治理，不等于开放式自主写入。

| # | 事项 | 完成标准 |
| --- | --- | --- |
| 1 | AgentRuntime Spike | 用“复习积压”场景比较原生 AgentKernel 与 LangGraph；验证 SQLite/PostgreSQL 持久化、SSE、暂停/恢复、取消、重试、草案确认、用户隔离、回放、成本和桌面分发；未通过则继续原生 Kernel |
| 2 | AgentKernel 单一纵向闭环 | 一个主动触发场景完成多步只读工具调用、SSE 步骤、行动草案、用户确认执行、旧 Planner fallback、执行日志回放；运行时选型未收口前不能替代旧 Planner |
| 3 | 后台调度器 MVP | 先支持一个触发器（复习积压）的启动/恢复 catch-up；明确生命周期、幂等键、锁、重试、超时、时区、免打扰和多实例语义；所有触达经 Coach 治理 |
| 4 | 干预效果自学习 v0 | 先落不可变曝光、接受/执行和后续行为事件；定义归因窗口和四项指标；确定性分桶统计先于 bandit，并置于 feature flag 后 |
| 5 | 知识巩固与周报 | 先定义扫描范围、去重、来源追溯和 Obsidian 文件所有权；生成可回滚草案，再实现写回；夜间任务必须可取消、可重试、可观测 |

阶段验收：一次典型干预可完整回放"为何触发、依据什么、展示给谁、用户是否接受/执行、后续行为变化"；失败、取消、重试和降级也有状态记录。只有该证据和灰度指标齐全才算 Phase 2 完成。

## 6. Phase 3：生态

| 事项 | 说明 |
| --- | --- |
| MCP Server | 暴露画像/图谱/错题/复习状态给外部 AI 客户端 |
| 语音 | TTS 朗读激励与提醒 → 按住说话 STT → 全双工对话（依次评估） |
| AnkiConnect | 评估用真 Anki 承载复习界面 |
| 一键 Demo | 示例数据 + 快速体验（沿用需求基线 P2） |
| 发布自动化 | 版本、构建、Release 资产、清单自动化 |

## 7. 冻结清单（默认不做）

- Markdown 编辑器新功能（保留现状供独立使用）。
- 新增业务页面（除非能回答"降低了哪个行为的执行阻力"）。
- 任何站点音视频下载功能（合规替代：本地音频导入 + B 站官方 iframe 嵌入）。
- 多人共学（沿用需求基线 P2 前置条件：先完成权限、隐私与授权设计）。
- 在 AgentRuntime Spike 未通过前，不锁定通用 agent 框架；`earendil-works/pi` 继续不引入，LangGraph 只作为受控候选，不得绕过 Mnemox 的权限、Coach 和草案确认。
- Microsoft GraphRAG 不纳入运行时或离线索引；LightRAG 只作评估与参考，不进入依赖树。
- 不把 Cognee、Mem0、Graphiti、Qdrant 或 Neo4j 作为用户事实、掌握度或权限的唯一来源。
- 在没有数据迁移、归因链路和回滚开关前，不引入 bandit 或其他在线策略学习。

## 8. 维护约定

- 每个阶段收口：更新本文件状态、`progress.md` 快照，并在 `docs/updates/` 记录周期变更。
- 顺序原则：一条线收口再开下一条；跨阶段并行仅限"立即轨道 + Phase 0"。
- 决策变更（如 Spike 结论、框架取舍）必须新增或修订 `docs/superpowers/specs/` 决策文档，不允许只改代码不改文档；每次候选技术通过或否决都要保留可复现证据。
- 每个事项必须同时维护目标指标、范围/非目标、依赖、迁移、失败降级、测试证据、观测、灰度和回滚信息；代码存在不等于事项完成。
