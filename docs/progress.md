# Mnemox 项目进度

> 状态：维护中
>
> 更新日期：2026-09-04
>
> 当前发布版本：v1.3.0
> 当前阶段：正式发布候选验收准备 + Phase 2 受控纵向切片 + **Mnemox V2 Stage 7 工程收口完成**。Stage 6 的 Neo4j / Graphiti 默认 Runtime NO-GO 继续成立；Stage 7 在不改变 PostgreSQL / SQLite Canonical 的前提下完成 Optional Neo4j selector/readiness/fallback/rollout、Knowledge/Learning Path V1、Explainable Multi-hop Association V1 和 Graphiti Temporal/Episodic Slice。最终 Stage 0～7 Knowledge/Temporal 宽回归为 `149 passed, 1 warning`，真实 Neo4j/Graphiti 专项另有 `6 passed` 且显式真机运行，前端 `27 files / 93 tests`、production build 和 lint 全过；默认 Compose 不启动 Neo4j，`--profile graph` 才启用可选图服务。Graphiti 60/300 temporal declarations correctness 均 `1.0` 但显著慢于 SQL，继续 Experimental/default-off。下一步转入云端 WebUI dogfooding，导入用户自己的真实技术笔记做中文/双语产品人评，而不是继续堆 Stage 7 基础设施。

需求范围见 [需求基线](requirements.md)，工程实现见 [技术基线](technical.md)，执行顺序以 [路线图](roadmap.md) 为唯一权威来源。

## 1. 当前阶段

Mnemox 已具备基础学习工作台、AI 对话、FSRS 复习、Agent/Coach 原型，以及 Phase 1 的学习证据、用户概念状态、同事务 projection outbox、Vault 安全同步和 SQL 记忆声明。2026-08-22 合入的 [PR #8](https://github.com/wlohf/Mnemox/pull/8) 将资料、笔记、记忆、概念和学习者状态收敛到 `RetrievalRouter`；随后 [PR #9](https://github.com/wlohf/Mnemox/pull/9) 将资料投影生命周期、质量门禁及 Qdrant no-go 合入 `main@2a54349`。

随后 [PR #10](https://github.com/wlohf/Mnemox/pull/10) 完成概念图谱和学习推荐闭环：资料正文自动生成待审核概念、括号别名、先修关系与版本化来源；更新/删除同步清理旧图谱证据，人工可确认、改名、合并、拆分或删除。错题创建和复习自动回填概念与直接学习证据；学习建议按已确认先修、FSRS 到期、活跃目标、错误频率、遗忘风险与重复疲劳解释排序。

当前增量完成 SQL 时态记忆生命周期：稳定事实键和部分唯一索引保证每个用户、每个事实只有一条开放的已确认声明；跨来源冲突进入人工审核，确认前旧事实继续生效，确认后保留严格的替代时间边界。用户可填写纠错原因、设置有效期、拒绝不准确候选和追溯完整历史；到期或删除会同步退出聊天、Coach、Agent 和引用旧事实的派生画像。Qdrant、Neo4j 与 Graphiti 均不作为当前运行时依赖。

本轮 Coach 闭环新增独立行动尝试：建议被展示、采纳和开始后会取得一个只属于该建议的关联标识；番茄钟开始/完成/中断、复习完成和日计划草案确认会在同一事务中把真实领域事件回连到该标识。无法由系统直接观察的动作仍保留用户“确认完成/不继续”的明确回退。建议详情可回放触发信号、行动尝试和最小化后的事件时间线；策略统计与北极星指标区分真实领域行为和用户确认。计划草案仍必须由用户确认才会写入。

2026-09-02 的 Mnemox V2 Stage 0 已固定 Claim 中心知识图谱的实施契约。两份脱敏合成语料提供 50 个带人工 Claim/Evidence 标注的 Unit 和 56 个跨来源联想问题；离线 runner 直接运行现有 Association V1。显式场景 Recall@5/MRR 为 `1.0`，隐式场景为 `0.0`，跨用户泄漏和删除残留为 `0`，两次结果摘要一致且外部模型调用为 `0`。九个 V2/Neo4j/Graphiti 开关全部默认关闭，抽取预算与长度/超时边界已记录。

同日按产品负责人明确授权完成 Stage 1：新增 `knowledge_sources`、`knowledge_source_revisions`、`knowledge_units`、`claims` 和 `claim_evidence` 五张规范 SQL 表及迁移 `20260902_19`。开启总开关时，Material、Note、Obsidian 导入/同步和受控 Agent/演示写入会在原事务登记稳定来源、不可变版本和可定位 Unit；重复内容不制造新版本，内容更新使旧版本和旧 Claim 失效，删除会先 tombstone 并清除正文/摘录。手工 Claim 只能绑定当前用户、当前来源版本及能在原文精确定位的 Evidence；没有 Evidence 的 Claim 不能确认为可见。Stage 1 不启动自动抽取、不写 Claim 关系、不改变 Association V1，也不安装或运行 Neo4j/Graphiti。二者已作为默认关闭、可重建的 Shadow 候选登记，实际关系能力要等 Stage 3～4 形成真实 Claim 图后再接入验证。

2026-09-03 按本轮明确授权完成 Stage 2：规则与可选 LLM 共用严格 Pydantic Extraction Schema；Evidence 采用精确后归一的定位流程，找不到原文位置的候选不写入，所有自动 Claim 保持 `pending`。新增迁移 `20260903_20` 和 `knowledge_extraction_runs`，提供幂等输入身份、租约、过期回收、有界重试、取消、usage/统计和 Unit 级 partial；PostgreSQL 用 `SKIP LOCKED` 协调多实例，SQLite 只启动单个应用内消费者。Material/Note 在总开关开启时创建本地确定性 run，LLM 仍需独立开关；缺少 AI Key 不影响资料保存或规则抽取。资料侧栏仅展示抽取状态与待审核数。Stage 2 不持久化 ClaimRelation，不实现 Entity Resolution、Association V2 或图运行时。

同日继续完成 Stage 3：迁移 `20260903_21` 新增解析候选、Claim-Concept 链接、四类对象的知识 embedding 投影元数据和 compact outbox。canonical/alias exact 与既有同来源人工决定可以自动确认；词法/向量候选只进入人工队列，绝不自动合并 Concept。知识 Chroma namespace 与资料 chunk 分离，所有命中必须回 SQL 复核当前用户和 active/confirmed 状态；配置、模型或维度变化会删除旧 collection 投影并从规范 SQL 重建。资料侧栏提供最小审核抽屉；Chroma、Key 或超时故障时，exact/alias 与 SQL 审核路径保持可用。Stage 3 不实现 ClaimRelation、Association V2、`SqlGraphStore` 或外部图运行时。

当前开发基线仍不是新版安装包。候选版本一致性、完整 CI、Windows 签名、安装包哈希和静默安装布局已形成独立自动门禁；本地历史 PostgreSQL 16 dump→restore→head 升级已完成，但正式 PostgreSQL 升级、远程候选 CI、真实 Windows Electron 启动/安装/升级 E2E、真实 Vault 冲突/删除和版本发布仍需按[正式发布验收](release-acceptance.md)执行。

当前新增的 AgentRuntime v0 不启用开放式自主写入：只有用户在设置中明确打开“定时评估”后，服务端才低频检查复习积压；每位用户持久化上次/下次评估和失败次数，成功、跳过与失败都保留可回放任务，失败使用有上限的指数退避。启动时会补扫尚无下次时间或已经到期的用户；每位用户可配置 IANA 时区，跨午夜免打扰会把评估原子延后到本地结束点，不创建任务或日志。单用户执行有硬超时，取消当前事务后进入安全重试；PostgreSQL 多实例用偏好行锁和 `SKIP LOCKED` 跳过正在处理的用户，幂等运行键继续充当第二道保护。Coach 的“今天”统计也按该时区的 UTC 边界计算。它把一条受 Coach 冷却、每日上限、稍后提醒和负反馈约束的建议放入 Agent 面板，不会自动开始番茄钟、修改计划、创建任务或发送网页推送。Agent 页还提供调试态的多步只读 AgentKernel：任务会先持久化，每个已完成工具步骤都保存受限上下文 checkpoint，短租约由当前执行实例续期；进程中断后，启动检查和常驻回收器只回收已过期租约，旧实例不能覆盖回收结果。步骤日志通过按用户隔离的 SSE 实时订阅，断线重连从数据库回放；运行中可协作取消，失败或取消后由用户确认从下一模型步骤精确继续。完成后的 Kernel 建议只能先生成用户自有的持久确认凭据；确认接口不接收前端草案正文，而从凭据快照重建并重新验证目标归属，原子幂等状态保证重复确认不重复创建任务。系统不会在无人确认时恢复模型调用或执行写入。“本周复盘”草案同样不写入学习数据。

2026-09-01 的用量对账切片保留“估算用于调用前硬停止、供应商 usage 用于调用后对账”的双轨语义。OpenAI-compatible、Claude 和 Gemini 的非流式响应会归一化真实输入/输出 Token；每次 Kernel 尝试分别持久化真实、估算和未取得 usage 的调用数，恢复时只累计本次增量。用户可为自己的 Provider 配置每百万输入/输出 Token 美元单价，系统据此计算参考成本；缺少单价时不猜价，缺少供应商 usage 时仍以保守估算计入预算。该参考成本不是供应商发票，真实密钥/账单环境验收仍待候选门禁。

同日完成旧 Planner 的规则降级产品化：Provider 不可用、模型错误、格式/步数失败或预算耗尽时，不再只返回空失败页，而是从稳定规则简报生成最多三条明确标注 `rules_fallback` 的行动。原 Kernel 任务仍保持失败状态和 checkpoint，可供用户稍后继续；降级行动则可立即进入同一套服务端草案、目标归属复核、确认凭据和幂等执行链路。取消、租约丢失和持久化异常不会自动生成行动，避免把并发/存储故障误当作正常降级。

干预效果自学习 v0 现以默认关闭的 A/A 观察开关落地。开启后，用户按实验 ID 和版本稳定进入 control 或 shadow 桶，但两组执行完全相同的 Coach 策略；分桶元数据随建议写入不可变生命周期事件，不包含用户标识、建议标题或正文。用户级报告只把已完整经过 7 天归因窗的曝光计入接受、开始、完成、真实领域完成、放弃和拒绝统计，并单列仍在归因中的曝光与历史未埋点覆盖。报告固定标记 `policy_behavior_changed=false` 和 `decision_readiness.ready=false`，不会依据小样本或相关性自动调参；Agent 页仅在服务器显式启用开关时展示观察状态。

知识巩固周报已完成第一条安全纵向切片：服务按用户 IANA 时区计算本地自然周的 UTC 半开扫描范围，只读取当前用户最近的笔记、已完成复习和错题线索，并排除其他用户、上周数据及 vault 中已标记 `missing` 的笔记。每条来源带稳定类型/ID/观察时间、内容版本指纹、页面路由和 `mnemox` / `obsidian_read_only` / `obsidian_conflict` 所有权；这些来源连同复盘结论形成稳定内容哈希与草案键，输入不变即可重复生成，来源变化会产生新键。Agent 页展示有限来源摘录并允许复制 Markdown；服务不会创建笔记、修改计划、隐式计算画像或回写 Obsidian，关闭或丢弃草案即完成回滚。四层路由的资料/概念/时态记忆扩展和任何写回协议仍未开放。

底层事务契约现已先在用户画像投影和 Agent 只读工具落地：`compute_and_save_profile` 只在当前 SQLAlchemy unit of work 中计算、upsert 和 `flush`，不再从服务层提交调用方事务；请求、后台 worker 或批处理入口统一决定何时 commit/rollback。过期画像刷新在 savepoint 中隔离失败，避免一次派生计算破坏外层事务；番茄钟提交后的独立画像 worker 显式提交并在失败时回滚。学习快照只读取已有画像，不再因为组装 Agent/Coach 上下文而产生隐式写入。`AgentManager.call_chat_tool` 同样只 flush 审计日志，避免 AgentKernel 的一次只读查询提前提交 checkpoint 或其他待处理状态。相关回归证明调用方回滚会同时撤销画像、工具日志和同事务业务数据。

画像首次写入的并发地基也已加固：PostgreSQL 与 SQLite 不再通过“先查、再插入/更新”决定写法，而是直接以 `user_profiles.user_id` 执行原子 upsert；两个请求同时首次生成同一用户画像时由数据库唯一约束仲裁。冲突更新使用显式字段所有权清单，不覆盖学习风格、AI 评估等其他画像生产者字段；服务仍保持 flush-only，未重新取得调用方事务的提交权。

为防止事务边界随着后续功能重新扩散，服务和 Agent 目录现有的每个 `.commit()` 都必须登记到事务所有权清单，并归类为跨存储恢复检查点或独立 worker 短事务。AST 架构门禁会同时拒绝未登记的新提交和已经不再存在的过期白名单；画像计算、学习快照和 Agent 只读工具另有反向约束。资料/检索跨 SQL 与向量库的提交点因此变成显式待收敛 saga，而不再是无法盘点的隐式副作用。

检索投影首次创建也已从“先查后插”改为 PostgreSQL/SQLite 原子冲突处理：数据库现有的用户/来源/后端唯一约束直接仲裁身份，每次确保后重新读取唯一生命周期行。重复或并发首次索引不会创建第二条 `retrieval_projections`，且不需要新增迁移。

长耗时检索变更现已增加同用户 fencing：SQLite/单进程用本地锁，PostgreSQL 用独立连接持有 session advisory lock，因此 manifest 与终态之间的提交不会释放顺序边界。等待完成后会重新读取规范 `materials`，旧 ORM 快照不能覆盖新版本；整用户 rebuild/purge 与单资料 ingest/forget 使用同一边界。取消或解锁失败不会把仍持锁的物理连接送回池。真实 PostgreSQL 的锁持有/释放断言已加入候选门禁，本地环境仍按外部专项跳过。

同一轮还建立了共享 UTC 时间契约：数据库时间继续使用兼容 SQLite/PostgreSQL 的 naive UTC，所有带偏移输入先换算到 UTC 后再去除 `tzinfo`，Agent、Coach、学习事件、记忆声明、画像、学习快照、检索投影和 projection outbox 的 API/健康快照时间统一输出 RFC 3339 `Z`。这些链路的“今天”不再依赖服务主机本地时区；Coach 免打扰、自然周和每日上限仍通过显式 IANA 用户时区计算 UTC 半开边界。旧报表中为兼容历史数据而明确采用本地墙上时间的统计语义暂不改动，后续须独立迁移并核对历史结果。

错误诊断边界也已统一：新的安全错误工具会在截断前清除 Authorization/Bearer、常见 API Key/Token/密码字段、URL 凭据与查询密钥、常见供应商 Token、JWT 和私钥块，并把控制字符与多行上游响应压成有界单行。Agent 失败任务与日志、Planner fallback、RAG 状态、检索投影、projection outbox、后台 worker、AI/RAG API 错误和关键降级日志已接入；关键任务不再把原始异常 traceback 直接写入日志。现有 Agent/outbox/检索投影读取边界也会再次脱敏，避免旧错误正文经 API 返回。

同一诊断边界现已增加结构化契约：错误码由业务调用点按恢复动作定义，摘要先脱敏限长，16 位关联指纹只对错误码和安全摘要计算。Agent 失败任务、RAG、检索投影、outbox/DLQ 与两个常驻 worker 已接入；worker 公开健康状态继续隐藏正文，只暴露类别和指纹。`[REDACTED]` 占位符的二次处理也已幂等，历史行读取不会因重复脱敏改变摘要或关联结果。

数据库中更早的诊断行现已具备受控清理路径：命令默认 dry-run 并只输出各表聚合计数，显式 `--apply` 后才由命令入口提交；底层服务分页 flush 但不拥有 commit，因此整批仍可回滚。清理只覆盖失败任务/日志的已知诊断键和两个投影的 `last_error`，不会递归修改 payload、用户业务正文或成功记录；重复运行保持幂等。外部集中日志、备份与历史导出仍需单独制定保留和访问策略。

运行时兼容边界同步清理了 Pydantic v2 的字段集合弃用警告：目标/任务、对话和笔记更新统一通过共享帮助函数读取 `model_fields_set`，仅在 v1 环境回退旧属性。显式 `null` 与未提供字段的更新语义保持不变；专项已在把弃用警告提升为错误的模式下通过。

为避免把“没有真人数据”误解为“无法测试”，开发基线另有隔离的虚拟学习者回放：固定场景覆盖建议的真实领域完成/用户确认/放弃、归因窗口、中断恢复、复习按时率、有效学习时段，以及复习积压触发、冷却和“太打扰”抑制。它直接通过真实事件账本和指标服务计算，但明确只作为回归测试，不能用来证明策略对真人有效或升级学习者模型版本。Agent 页面现在也展示四项行为指标及其观察范围，后台运行只在生成实际建议或失败重试时留下简洁记录。

## 2. 当前交付快照

| 范畴 | 状态 |
| --- | --- |
| 版本与发布 | `v1.3.0` 仍是唯一当前正式版本；已新增可重复的候选验收 workflow 和发布前置检查，且会拒绝新提交复用旧 tag。尚未选择下一版本，tag、GitHub Release 和公开安装资产保持不变。 |
| 统一检索 | `RetrievalRouter` 统一资料、笔记、概念、记忆与学习者状态；主聊天、ChatAgent、AgentKernel 和资料搜索均通过路由查询。 |
| 检索生命周期 | `retrieval_projections` 与 `retrieval_projection_chunks` 记录来源版本、配置指纹、状态、错误和分块；支持 ingest、refresh、forget、retry、rebuild 和用户隔离。 |
| 检索质量 | 16-case 固定质量集覆盖 Recall@5/10、MRR、NDCG、延迟、跨用户泄漏、删除残留、空查询和无 embedding 降级；hybrid Recall@5 为 `0.9833`。 |
| Qdrant 决策 | 真实 Qdrant Local 比较 dense+sparse+RRF、轻量词项重排和 sparse-only fallback；未满足明显优势门槛，不加入运行时依赖。 |
| 概念图谱 | SQL 概念、别名、五类关系、来源摘录、审核和操作审计已接入；支持资料更新/删除清理、人工身份治理、错题回填、先修缺口和跨用户/环路拦截。 |
| 学习推荐 | 强弱证据分别约束掌握与风险；状态保存答题/正确/提示计数，并结合 FSRS、目标、错误和已确认先修生成只读、逐项可解释的下一步建议。 |
| 时态记忆 | 稳定事实键、当前事实部分唯一约束、历史重复回填、冲突审核、旧事实保留、确认替代、纠错原因、到期失效、全入口过滤、派生画像删除和跨用户隔离均已实现。 |
| Mnemox V2 Stage 0～7 | ✅ **Stage 7 工程收口完成。** Stage 0～5 工程主链已收口；Stage 6 的 Neo4j/Graphiti 默认 Runtime NO-GO 证据保留；Stage 7 完成 Optional Neo4j Runtime、Knowledge/Learning Path V1、Explainable Multi-hop Association V1、Graphiti Temporal/Episodic Slice、默认/graph Compose 边界、真实 Neo4j/Graphiti integration 和 Architecture Story。最终宽回归 `149 passed, 1 warning`；真实 Neo4j Shadow/Knowledge Path `4 passed`，真实 Stage 6/7 Graphiti 各 `1 passed`；前端 `27 files / 93 tests` + build/lint 通过。Graphiti V1 不摄入 staged conflict/聊天原文，外部 LLM/embedding/reranker 调用为 0；60/300 temporal declarations correctness `1.0`，但 p95 `192.20/138.55ms` vs SQL `4.77/2.92ms`，故继续 Experimental/default-off。真实技术笔记的人评移交 WebUI dogfooding。 |
| 数据库 | SQLite lightweight migration 与 Alembic 唯一 head 为 `20260903_21`；全新一次性 PostgreSQL 16 通过 `alembic check` 和 10 项候选门禁，其中包含 extraction/projection worker 的真实 `SKIP LOCKED`。另已把旧迁移点的固定历史数据用 PostgreSQL 16 `pg_dump -Fc` 恢复到新库、升级至 head，并通过数据保留专项与 drift 检查。正式源库仍未升级。 |
| 前端 | 资料侧栏展示检索投影、知识抽取和待审核 Claim/概念解析状态；概念解析抽屉支持关联、关联并新增别名、新建、忽略及转到概念合并页，已用真实 Chromium 检查桌面与 `390px` 窄屏；`/mastery`、`/memory` 与 `/agent` 保持既有能力。 |
| 主动 AgentRuntime v0 | 服务端低频 worker 只扫描已明确 opt-in 且到期的用户；首个场景为复习积压，具备启动 catch-up、IANA 时区、跨午夜免打扰延后、单用户硬超时、完成/跳过/失败任务、有界重试，以及 PostgreSQL `SKIP LOCKED` 多实例防重复代码门禁。多步只读 Kernel 另具备预备任务、短租约/过期回收、受限上下文 checkpoint、下一步精确续跑、SSE 实时订阅/断线回放、取消、用户隔离、供应商真实 Token/配置单价参考成本对账、可重试的规则 Planner 降级和基于持久凭据的幂等行动确认；Coach 自学习新增默认关闭、永不改策略的 A/A 观察与 7 天成熟归因报告；知识巩固周报新增用户/自然周隔离、稳定来源版本和 copy-only Markdown 草案。续跑和写入均要求用户确认。 |
| 本地回归 | 2026-09-03 后端 `549 passed, 15 skipped, 58 subtests passed`，Stage 0～3/迁移/事务关键组合专项 `64 passed`；全新 PostgreSQL 16 候选门禁 `10 passed`，历史 dump 恢复升级专项 `1 passed`，`alembic check` 无 drift。前端 `27 files / 93 tests passed`，build、lint 与桌面/窄屏 Chromium 检查通过；桌面端最近一次为 `22 passed`。Stage 3 记录式合成 Top-5 Recall `1.0`、跨用户和自动语义合并 `0`，但尚未完成真实 embedding provider 质量抽样。版本一致性 preflight 通过；远程候选 workflow 仍待执行。 |
| 已通过 CI | PR #8、PR #9、PR #10 与 [PR #11](https://github.com/wlohf/Mnemox/pull/11) 均已通过 Backend、Frontend、PostgreSQL 16、多 worker、Chromium、Windows smoke 和 Repository integrity；新增时态记忆迁移已完成真实 PostgreSQL 16 验收。 |

## 3. 已通过的远程验收

PR #8 于 2026-08-22 07:32 UTC 合入 `main@5da524c`，对应 [GitHub Actions run 32559668354](https://github.com/wlohf/Mnemox/actions/runs/32559668354)。随后 PR #9 合入 `main@2a54349`，对应 [GitHub Actions run 32564219532](https://github.com/wlohf/Mnemox/actions/runs/32564219532)。SQL 时态记忆 [PR #11](https://github.com/wlohf/Mnemox/pull/11) 对新增 `20260823_12` 迁移再次执行并通过全部门禁，对应 [GitHub Actions run 32633212169](https://github.com/wlohf/Mnemox/actions/runs/32633212169)。每次远程验收中的六个任务均成功：

1. Frontend / Node 20。
2. Repository integrity。
3. Desktop / Windows / Node 20 smoke。
4. PostgreSQL 16 / migration and multi-worker acceptance。
5. Backend / Python 3.11。
6. Browser / Chromium / critical paths。

其中 PostgreSQL 任务已实际执行空库升级、`SKIP LOCKED`、共享重试策略、双 worker exactly-once、独立心跳和 `alembic check`；Chromium 已实际验证 Agent 草案取消无副作用、确认后恰好执行一次。上述结果不再标记为“待执行”。正式生产数据库升级和真实桌面安装验收仍未完成。

## 4. 检索质量与技术选型

| Backend | Recall@5 | MRR | NDCG@10 | P95 |
| --- | ---: | ---: | ---: | ---: |
| SQL keyword | 0.9833 | 1.0000 | 0.9158 | 13.69 ms |
| Chroma dense | 0.8500 | 0.8800 | 0.7782 | 8.19 ms |
| Chroma + keyword + RRF | 0.9833 | 0.9667 | 0.8782 | 9.12 ms |
| Hybrid，无 embedding | 0.9833 | 1.0000 | 0.9158 | 6.53 ms |
| Qdrant dense + sparse + RRF | 0.9500 | 0.9667 | 0.8912 | 12.79 ms |
| Qdrant + 轻量词项重排 | 0.9833 | 0.9667 | 0.8932 | 9.38 ms |
| Qdrant sparse-only | 0.9833 | 1.0000 | 0.9158 | 5.04 ms |

所有后端的跨用户泄漏、删除后残留均为 0，空查询兼容。该质量集使用小型合成语料和确定性本地 embedding；延迟为单次进程内采样，不能外推为生产性能或 Windows 打包证据。详细步骤、约束和 no-go 决策见 [检索生命周期与质量 ADR](superpowers/specs/2026-08-22-retrieval-lifecycle-quality-adr.md)。

```bash
cd backend
python evaluate_retrieval.py --backend hybrid --min-recall-at-5 0.75 --summary-only
pip install -r requirements-spike.txt
python evaluate_retrieval.py --backend all --include-qdrant --summary-only
```

常规 CI 只运行现有生产 hybrid 质量门禁；Qdrant 依赖和实验明确保持可选。

本地全量回归的 15 个跳过项均属于当前环境未提供的外部平台、真实凭据或可选依赖专项；本轮另用一次性 PostgreSQL 16 完成 Stage 3 本地数据库门禁与历史 dump 恢复升级，远程候选验收仍须由 GitHub Actions 执行。Qdrant 继续只保留为已否决的可选 Spike，不进入发布运行时。

## 5. 历史验证与发布边界

- v1.3.0 发布时后端为 `152 passed, 53 subtests passed`，前端为 `19 files / 60 tests passed`，桌面端为 `21 passed`。
- 2026-08-05 完成学习者模型、同事务 outbox、525 条事件分页重放、SQLite/Alembic 升级和一次性 PostgreSQL 16 数据保留演练。
- 2026-08-13 完成 Phase 1 主线整合与 outbox 运维收口；聚焦后端回归为 `61 passed`，前端为 `22 files / 67 tests passed`。
- 2026-08-19 通过 PR #5 收敛 ContextStore、Coach 归因、Vault 安全和 SQL 记忆声明；当时 head `20260816_09` 仅为历史记录，不是当前数据库版本。
- 2026-08-22 PR #8 交付统一 `RetrievalRouter`，并完成 PostgreSQL 16、Chromium 和 Windows smoke 的真实远程 CI 验收。
- 2026-08-22 PR #9 完成 SQL 检索投影、更新/删除/重建生命周期、状态 UI、离线质量门禁与 Qdrant no-go。
- 当前增量完成可审核 SQL 概念图谱、来源生命周期、身份治理、先修缺口、错题/FSRS 证据回填及解释型推荐；尚未单独创建新版 tag、安装包或 GitHub Release。
- 2026-08-23 完成 SQL 时态记忆事实身份、部分唯一约束、冲突审核、确认替代、纠错原因、自动失效和派生画像清理；Graphiti 不进入运行时依赖。
- 2026-09-03 完成 Mnemox V2 Stage 0～3：在 Claim 评测契约、规范 SQL、统一抽取和可恢复 run 之上，新增不自动语义合并的 Entity Resolution、ClaimConceptLink、知识专用 Chroma 投影、compact outbox 与人工审核；SQLite/PostgreSQL 门禁及本地历史 dump 恢复升级已通过。
- 2026-09-04 完成 Mnemox V2 Stage 6：Neo4j / Graphiti 均完成真实 SDK/数据库 Shadow 门禁并得出“默认 Runtime NO-GO”；原因是当前净收益与运维成本门槛失败，而非正确性失败。同日新增图架构演进决策：为了真实 graph-native 产品能力、系统学习与工程作品集价值，Stage 7 重新打开为 Optional Neo4j Backend + Graphiti Temporal Slice，默认产品路径仍保持 SQL。

## 6. 下一阶段执行顺序

1. **发布候选验收**：选择 `v1.3.0` 之后的新版本，在干净候选提交上运行完整远程 CI、签名 Windows 构建、哈希和静默安装门禁；随后完成真实 Electron E2E。本地历史 PostgreSQL 恢复升级已通过，不替代发布窗口中的正式快照核验。
2. **AgentRuntime 单场景验收**：验证 opt-in 的“复习积压 → Agent 面板建议 → 用户确认草案 → 行动/反馈 → 回放”链路，以及 Kernel SSE、租约过期回收、checkpoint 精确续跑、取消、失败重试和规则 Planner 降级；预算会在调用前硬停止，调用后会归一化供应商真实 usage 并按用户配置单价计算参考成本。下一步补真实密钥/账单抽样核对与原生/LangGraph 对照，不扩大到开放式自动执行或通用多 Agent。
3. **生产升级与发布**：候选全部通过后，冻结写入、保留快照、显式升级正式源库，再创建新 tag、Release 和公开安装资产；全过程按[正式发布验收](release-acceptance.md)停止条件执行。
4. **云端 WebUI dogfooding / 真实笔记人评**：Stage 7 工程收口已完成。下一步优先准备云端可测试入口，让用户直接导入自己的中文/英文技术笔记，观察 Claim、Concept/Relation、Association、Knowledge Path、Multi-hop explanation 与 Temporal Memory 的真实效果；真实人评结果与长期灰度数据单独记录，不回写成 Stage 7 合成工程结论。默认部署继续不强制 Neo4j/Graphiti。
5. **Mnemox V2 Stage 4/5 真实质量验收**：继续并行补真实匿名中文/双语语料、真人牵强率和产品灰度。Graph backend 深化不能替代产品质量验收。

Stage 6 的“双 NO-GO”继续作为重要历史证据：它回答的是“是否应该默认切流”；Stage 7 的重新打开回答的是“是否值得把目标技术做成真实可选能力并承载 graph-native 场景”。两者不冲突。
