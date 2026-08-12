# Mnemox 项目进度

> 状态：维护中
>
> 更新日期：2026-08-12
>
> 当前版本：v1.3.0
> 当前阶段：Phase 1 学习者模型和 Outbox 运维闭环已收口；真实数据校准与其余底座进行中；Phase 2 等待 Phase 1 验收

本文件记录可执行的项目状态。需求范围见 [需求文档](requirements.md)，工程实现见 [技术文档](technical.md)，按周变化记录见 `docs/updates/`。

## 1. 阶段判断

Mnemox 已完成核心学习工具、个性化学习闭环、Agent/Coach 和 Windows 桌面交付的第一轮实现。当前处于 **v1.3.0 的 Beta/Phase 1 生产化阶段**：默认 SQLite 升级和一次性 PostgreSQL 演练已完成；学习者模型、同事务 projection outbox、分页重放、API、前端证据下钻、校准基线和 PostgreSQL 常驻 worker 均已验证。Outbox 的显式 DLQ、用户范围人工重试、告警代码、受保护活跃队列指标和运行时唯一跨实例心跳已收口。下一步是积累真实 holdout 数据，并按发布窗口完成真实 PostgreSQL 多实例验收；Phase 2 不提前展开。

2026-07-26 完成方向基线梳理；2026-08-03 进一步将资料检索、概念关系、时态记忆和学习者模型拆为四层，并固化规范数据、事件投影和候选技术 Spike 的边界，见 [学习智能底座架构决策](superpowers/specs/2026-08-03-learning-intelligence-foundation-architecture.md)。2026-08-05 已完成学习者模型首个垂直切片的正确性收口，包括 projection outbox、批量重放/API、默认 SQLite 升级、一次性 PostgreSQL 演练、前端证据下钻和校准基线；阶段顺序仍以 [路线图](roadmap.md) 为唯一权威来源，候选组件仍未引入。

## 2. 当前交付快照

| 范畴 | 状态 |
| --- | --- |
| 版本与发布 | `v1.3.0` 已发布；`origin/main`、版本 tag、GitHub Release 和 Windows 安装包（`Mnemox-Setup-1.3.0.exe`、`latest.yml`、blockmap）已存在；当前 feature 分支的 Phase 1 改动尚未作为新版本发布。 |
| 后端能力 | 30 个路由模块、25 个模型模块、45 个服务模块，覆盖学习、AI、RAG、笔记上下文、学习者模型、事件投影、Agent 与 Coach。 |
| 前端能力 | 17 个业务页面，主工作台、学习工具、洞察、设置和笔记上下文提示均已接入。 |
| 桌面端 | Electron 壳、Windows NSIS 构建、更新器和桌面提醒桥接已存在。 |
| 自动化测试 | 后端 46 个测试文件；前端 19 个测试文件；桌面端 7 个测试文件。 |
| 当前工作分支 | `feature/phase2-agent-upgrade` 是历史分支名，不代表 Phase 2 已启动；当前优先级仍严格按 Phase 1 路线图执行。 |

## 3. v1.3.0 已完成

- 将本地 `feature/voice-rag-motivation-agent` rebase、审查并合并到 `main`。
- 聊天按当前用户、关键词、标题、标签和更新时间检索相关笔记。
- 检索笔记经过 Prompt Safety 包装与 1,800 字符预算限制，异常时自动降级为正常聊天。
- 流式聊天通过 SSE 返回笔记上下文指示器，前端提示本轮参考的笔记标题。
- 新增笔记检索排序、跨用户隔离、不可信上下文、指示器裁剪和聊天流式事件测试。
- 新增 `scripts/seed_showcase_account.py`，用于本地 Demo 账号和学习闭环数据准备。
- 建立需求、技术、进度三份项目基线文档，并接入根 README 与文档导航。

## 4. 发布前验证

| 模块 | 结果 |
| --- | --- |
| 后端 | `152 passed, 53 subtests passed` |
| 前端测试 | `19 passed files, 60 passed tests` |
| 前端构建与 lint | `npm.cmd run build`、`npm.cmd run lint` 通过 |
| 桌面端 | `21 passed` |
| 文档与 Git | 文档已接入导航，`git diff --check` 通过 |
| 演示脚本 | `seed_showcase_account.py --help` 加载和参数解析通过 |
| 本轮聚焦验证 | `backend/tests/test_agent_kernel.py` 单独运行 `9 passed`；相关测试合并运行曾超时，不能代替全量验收 |

## 5. Git 与 GitHub 状态

- 原本未合并的笔记上下文功能已进入 `main`。
- v1.3.0 发布提交、tag、GitHub Release 和 Windows 安装包已完成发布；后续 Phase 1 改动应单独走新的验证、提交和发布流程。
- `scripts/seed_showcase_account.py` 已纳入版本控制；它包含固定本地 Demo 凭据，只能用于本地演示，不能作为生产初始化方式。

## 6. 下一阶段工作

阶段顺序、完成标准与冻结清单以 [路线图](roadmap.md) 为唯一权威来源，此处仅保留执行快照：

| 轨道 | 主题 | 状态（2026-08-09 复核） |
| --- | --- | --- |
| 立即（小胜利） | 自引激励收尾（接入低动力 Coach 技能 + 防疲劳 + 反馈）、FSRS 替换 SM-2 调度 | 🔶 主体完成（FSRS 优先、SM-2 降级；版本化迁移、数据保留回归、PostgreSQL 离线 DDL 和一次性 PostgreSQL 16 演练已完成；正式生产升级按发布窗口执行） |
| Phase 0 | Beta 稳定化：授权审计、注入防护、RAG 可见化、关键路径验证、仓库卫生 | 🔶 部分完成（授权/注入/RAG 可见化主体和 API 冒烟已完成；真实浏览器 E2E、草案确认执行和卫生收口待补） |
| Phase 1 | 四层学习智能底座：数据契约、事件投影、ContextStore/Qdrant Spike、概念图/Neo4j Spike、时态记忆/Graphiti Spike、学习者模型、Obsidian 与联想 | 🔶 MVP 部分完成；学习者模型/outbox/API/前端证据下钻、离线校准基线、数据库演练、PostgreSQL 常驻 worker、DLQ/告警/跨实例指标已验证；统一检索迁移、候选 Spike、同步冲突/删除、Coach 联想反馈和真实数据质量评测待补 |
| Phase 2 | AgentRuntime：AgentKernel/LangGraph 受控比较、单一纵向切片、后台调度器、干预效果自学习、知识巩固与周报 | 🔶 AgentKernel 原型实现中；运行时 Spike、后台调度、自学习归因、指标看板、知识巩固和 Obsidian 写回未开始 |
| Phase 3 | 生态：MCP Server、语音、AnkiConnect 评估、一键 Demo、发布自动化 | 未开始 |

2026-08-01 迁移收口：新增冻结 v1.3 基线与 Phase 1 增量 Alembic 链；空库、严格指纹匹配的 v1.3 库和未知无版本库分别走升级、基线 stamp 后升级和拒绝三条路径。2026-08-04 增加 outbox 与 legacy schema alignment 修订，默认 SQLite 已备份并升级到 `20260804_03`；一次性 PostgreSQL 16 演练库完成 v1.3→head 升级，验证数据量、legacy 证据/状态、outbox 运行投影、外键和 `alembic check`。正式生产 PostgreSQL 仍需按发布窗口执行。

2026-08-05 最终聚焦验证：learner model + API + calibration 合计 `23 passed`；projection outbox `9 passed`（包含 525 条分页重放和事件级在线消费）；schema/learning event/north-star `9 passed`；前端 `21 files / 66 tests passed`、生产构建和 lint 通过。390px Playwright 检查 `scrollWidth=390`、无截断文本、0 个页面 error。

原 P1“闭环效果优化”中的 token 预算分层由 ContextStore 承接；当前只有接口和关键词保底，尚未完成业务迁移。2026-08-05 学习者模型与事件投影切片已完成收口：`learner_evidence` 是不可变可重放输入，`user_concept_state` 是带来源/可靠度/模型版本/更新时间/解释摘要的派生状态，`projection_outbox` 是同事务写入、可重试、可重放的投影任务；Review/Anki 完成复习会在请求事务内消费对应事件的投影，失败任务仍保留供恢复。前端已支持证据下钻和人工修正；校准报告对当前 0 个 holdout case 明确给出 `collect_more_data`。2026-08-06 已补 PostgreSQL 应用生命周期常驻 worker：每条任务独立事务提交，关闭数据库前停止，并在 `/health` 暴露本实例的非敏感运行统计；SQLite/桌面端继续使用请求内单消费者路径。2026-08-09 已完成 Outbox 运维闭环：`dead_lettered_at` 明确标记终态失败，用户可查看自己脱敏后的失败队列并显式重试；数据库中的版本化共享重试策略要求同一版本保持同一上限，升级版本后所有 DLQ-aware consumer 读取规范上限并双向对账终态失败；PostgreSQL worker 以独立非敏感心跳提供跨实例活跃/失活统计；公开 `/health` 只做轻量存活检查，私有 `/internal/outbox/metrics` 仅在部署配置 token 后提供聚合队列状态、规范策略版本和上限，告警通过 alert code、指标和状态变更日志承接。2026-08-12 将 `OUTBOX_WORKER_ID` 收敛为逻辑前缀并生成运行时唯一 ID，避免同前缀副本覆盖或停止彼此心跳；指标聚合限定在未完成队列并由局部索引支撑，不扫描 processed 历史；同版本不同重试上限的部署漂移会由只读私有指标和关键告警显式报告，活跃但持续轮询失败的 worker 也会通过 `error_workers` 和关键告警暴露，公开 `/health` 继续只承担轻量存活检查。真实 PostgreSQL 多实例并发验收仍保留在正式发布窗口。

## 7. 下一阶段执行入口

按以下顺序推进，每一项都要留下测试、迁移和验收证据：

1. **真实数据校准**：积累至少 50 个 holdout case 后运行 `backend/calibrate_learner_model.py`，比较三个模型版本；未达到门槛时保持 `collect_more_data`。
2. **`ContextStore` 首条真实链路**：迁移一条资料或笔记检索路径，保留关键词降级，并补更新、删除和用户隔离回归。
3. **Obsidian 同步一致性**：完成稳定文件 ID、删除与冲突策略和用户可见处理流程。
4. **Coach 联想反馈闭环**：记录 shown、accepted、executed 事件，为后续干预归因提供事实输入。
5. **记忆声明与时态记忆准备**：先建立可审核、可删除的 SQL 记忆声明，再决定是否做 Graphiti Spike。
6. **兼容与候选 Spike**：数据校准和兼容周期验收后，再规划移除 `Concept.mastery`；候选组件必须先完成可复现的 go/no-go 评估。
7. **Phase 2（等待 Phase 1 验收）**：再比较 AgentKernel 与 LangGraph，随后才进入 SSE/草案闭环、后台调度、自学习归因和知识写回。

发布层残余项不阻塞上述模块开发，但阻塞正式生产收口：真实浏览器/桌面端的“草案确认与执行”E2E，以及正式 PostgreSQL 升级窗口。
