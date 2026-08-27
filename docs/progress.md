# Mnemox 项目进度

> 状态：维护中
>
> 更新日期：2026-08-26
>
> 当前发布版本：v1.3.0
> 当前阶段：Phase 1 收口 + Phase 2 单场景纵向切片；统一检索、资料生命周期、可审核概念图谱、可解释学习推荐、SQL 时态记忆和 Coach 教学行为闭环已完成代码实现。AgentRuntime 已开始“复习积压”单场景的 opt-in 服务端切片，仍待真实用户行为验收后扩大范围。

需求范围见 [需求基线](requirements.md)，工程实现见 [技术基线](technical.md)，执行顺序以 [路线图](roadmap.md) 为唯一权威来源。

## 1. 当前阶段

Mnemox 已具备基础学习工作台、AI 对话、FSRS 复习、Agent/Coach 原型，以及 Phase 1 的学习证据、用户概念状态、同事务 projection outbox、Vault 安全同步和 SQL 记忆声明。2026-08-22 合入的 [PR #8](https://github.com/wlohf/Mnemox/pull/8) 将资料、笔记、记忆、概念和学习者状态收敛到 `RetrievalRouter`；随后 [PR #9](https://github.com/wlohf/Mnemox/pull/9) 将资料投影生命周期、质量门禁及 Qdrant no-go 合入 `main@2a54349`。

随后 [PR #10](https://github.com/wlohf/Mnemox/pull/10) 完成概念图谱和学习推荐闭环：资料正文自动生成待审核概念、括号别名、先修关系与版本化来源；更新/删除同步清理旧图谱证据，人工可确认、改名、合并、拆分或删除。错题创建和复习自动回填概念与直接学习证据；学习建议按已确认先修、FSRS 到期、活跃目标、错误频率、遗忘风险与重复疲劳解释排序。

当前增量完成 SQL 时态记忆生命周期：稳定事实键和部分唯一索引保证每个用户、每个事实只有一条开放的已确认声明；跨来源冲突进入人工审核，确认前旧事实继续生效，确认后保留严格的替代时间边界。用户可填写纠错原因、设置有效期、拒绝不准确候选和追溯完整历史；到期或删除会同步退出聊天、Coach、Agent 和引用旧事实的派生画像。Qdrant、Neo4j 与 Graphiti 均不作为当前运行时依赖。

本轮 Coach 闭环新增独立行动尝试：建议被展示、采纳和开始后会取得一个只属于该建议的关联标识；番茄钟开始/完成/中断、复习完成和日计划草案确认会在同一事务中把真实领域事件回连到该标识。无法由系统直接观察的动作仍保留用户“确认完成/不继续”的明确回退。建议详情可回放触发信号、行动尝试和最小化后的事件时间线；策略统计与北极星指标区分真实领域行为和用户确认。计划草案仍必须由用户确认才会写入。

当前开发基线仍不是新版安装包。正式 PostgreSQL 升级、真实 Windows Electron 启动/安装 E2E、真实 Vault 冲突/删除和版本发布继续单独验收。

当前新增的 AgentRuntime v0 不启用开放式自主写入：只有用户在设置中明确打开“定时评估”后，服务端才低频检查复习积压；它把一条受 Coach 冷却、每日上限、稍后提醒和负反馈约束的建议放入 Agent 面板。它不会自动开始番茄钟、修改计划、创建任务或发送网页推送。Agent 页新增“本周复盘”草案，以既有学习事件和北极星指标整理优点、风险和最多三条可选下一步，同样不写入学习数据。

为避免把“没有真人数据”误解为“无法测试”，开发基线另有隔离的虚拟学习者回放：固定场景覆盖建议的真实领域完成/用户确认/放弃、归因窗口、中断恢复、复习按时率、有效学习时段，以及复习积压触发、冷却和“太打扰”抑制。它直接通过真实事件账本和指标服务计算，但明确只作为回归测试，不能用来证明策略对真人有效或升级学习者模型版本。Agent 页面现在也展示四项行为指标及其观察范围，后台运行只在生成实际建议或失败重试时留下简洁记录。

## 2. 当前交付快照

| 范畴 | 状态 |
| --- | --- |
| 版本与发布 | `v1.3.0` 仍是唯一当前正式版本；tag、GitHub Release 和 Windows 安装资产保持不变。 |
| 统一检索 | `RetrievalRouter` 统一资料、笔记、概念、记忆与学习者状态；主聊天、ChatAgent、AgentKernel 和资料搜索均通过路由查询。 |
| 检索生命周期 | `retrieval_projections` 与 `retrieval_projection_chunks` 记录来源版本、配置指纹、状态、错误和分块；支持 ingest、refresh、forget、retry、rebuild 和用户隔离。 |
| 检索质量 | 16-case 固定质量集覆盖 Recall@5/10、MRR、NDCG、延迟、跨用户泄漏、删除残留、空查询和无 embedding 降级；hybrid Recall@5 为 `0.9833`。 |
| Qdrant 决策 | 真实 Qdrant Local 比较 dense+sparse+RRF、轻量词项重排和 sparse-only fallback；未满足明显优势门槛，不加入运行时依赖。 |
| 概念图谱 | SQL 概念、别名、五类关系、来源摘录、审核和操作审计已接入；支持资料更新/删除清理、人工身份治理、错题回填、先修缺口和跨用户/环路拦截。 |
| 学习推荐 | 强弱证据分别约束掌握与风险；状态保存答题/正确/提示计数，并结合 FSRS、目标、错误和已确认先修生成只读、逐项可解释的下一步建议。 |
| 时态记忆 | 稳定事实键、当前事实部分唯一约束、历史重复回填、冲突审核、旧事实保留、确认替代、纠错原因、到期失效、全入口过滤、派生画像删除和跨用户隔离均已实现。 |
| 数据库 | SQLite lightweight migration 与 Alembic 当前 head 为 `20260826_14`；新增 `coach_action_attempts` 与番茄钟关联字段，保留旧 SQLite 兼容路径。本地 SQLite 初始化、迁移和启动已复验；Coach 闭环仍待 PostgreSQL CI 复验。 |
| 前端 | 资料侧栏展示检索投影状态；`/mastery` 展示概念与学习建议；`/memory` 展示事实冲突对照、候选审核、有效期、纠错原因和跨投影历史；`/agent` 可生成不写入数据的本周复盘。 |
| 主动 AgentRuntime v0 | PostgreSQL 服务端低频 worker 只扫描已明确 opt-in 的用户；首个场景为复习积压，建议仅进入 Agent 面板，并持久化最小运行记录以便回放。 |
| 本地回归 | 后端 `414 passed, 8 skipped, 53 subtests passed`；前端 `25 files / 85 tests passed`；桌面端 `21 passed`；SQLite 初始化/迁移、后端健康检查、生产构建、类型检查、lint 和浏览器自测通过。 |
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

本地全量回归的 8 个跳过项为需要真实 PostgreSQL 服务的 4 个验收用例，以及未安装可选 Qdrant 依赖时的 4 个 Spike 用例。Qdrant 用例已在安装可选依赖后单独通过；真实 PostgreSQL 验收继续由 GitHub Actions 服务库执行。

## 5. 历史验证与发布边界

- v1.3.0 发布时后端为 `152 passed, 53 subtests passed`，前端为 `19 files / 60 tests passed`，桌面端为 `21 passed`。
- 2026-08-05 完成学习者模型、同事务 outbox、525 条事件分页重放、SQLite/Alembic 升级和一次性 PostgreSQL 16 数据保留演练。
- 2026-08-13 完成 Phase 1 主线整合与 outbox 运维收口；聚焦后端回归为 `61 passed`，前端为 `22 files / 67 tests passed`。
- 2026-08-19 通过 PR #5 收敛 ContextStore、Coach 归因、Vault 安全和 SQL 记忆声明；当时 head `20260816_09` 仅为历史记录，不是当前数据库版本。
- 2026-08-22 PR #8 交付统一 `RetrievalRouter`，并完成 PostgreSQL 16、Chromium 和 Windows smoke 的真实远程 CI 验收。
- 2026-08-22 PR #9 完成 SQL 检索投影、更新/删除/重建生命周期、状态 UI、离线质量门禁与 Qdrant no-go。
- 当前增量完成可审核 SQL 概念图谱、来源生命周期、身份治理、先修缺口、错题/FSRS 证据回填及解释型推荐；尚未单独创建新版 tag、安装包或 GitHub Release。
- 2026-08-23 完成 SQL 时态记忆事实身份、部分唯一约束、冲突审核、确认替代、纠错原因、自动失效和派生画像清理；Graphiti 不进入运行时依赖。

## 6. 下一阶段执行顺序

1. **Coach 教学行为闭环验收**：本地 SQLite 迁移、番茄钟/计划确认归因、回放单测和前端验证已通过；继续复验公网真实浏览器三条路径，积累真实样本，不把相关性误称为因果。
2. **AgentRuntime 单场景验收**：当前先验证 opt-in 的“复习积压 → Agent 面板建议 → 用户行动/反馈 → 回放”链路；不要扩大到自动执行、通用多 Agent 或桌面推送。
3. **生产验收与版本发布**：完成正式 PostgreSQL 升级、备份回滚、真实 Windows Electron 启动/安装/升级 E2E、真实 Vault 冲突与删除、版本号、tag、Release 和安装包。

当前不进入多 Agent、语音、MCP 或其他生态扩展。
