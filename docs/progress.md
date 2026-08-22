# Mnemox 项目进度

> 状态：维护中
>
> 更新日期：2026-08-22
>
> 当前发布版本：v1.3.0
> 当前阶段：Phase 1；统一检索、资料投影生命周期、质量门禁与 Qdrant 选型已完成，下一模块为概念图谱自动抽取、人工编辑与先修缺口闭环。

需求范围见 [需求基线](requirements.md)，工程实现见 [技术基线](technical.md)，执行顺序以 [路线图](roadmap.md) 为唯一权威来源。

## 1. 当前阶段

Mnemox 已具备基础学习工作台、AI 对话、FSRS 复习、Agent/Coach 原型，以及 Phase 1 的学习证据、用户概念状态、同事务 projection outbox、Vault 安全同步和 SQL 记忆声明。2026-08-22 合入的 [PR #8](https://github.com/wlohf/Mnemox/pull/8) 将资料、笔记、记忆、概念和学习者状态收敛到 `RetrievalRouter`，并接入主聊天、ChatAgent 和 AgentKernel。

本轮继续完成资料检索的完整投影生命周期：规范资料和 SQL chunk 清单先持久化，Chroma 向量随后生成；资料更新替换旧版本，删除保留可恢复墓碑，embedding 不可用时降级为 SQL 关键词检索，失败可重试，按用户可重建或清除。16 条离线问题组成可重复运行的质量集；真实 Qdrant Local dense+sparse+RRF 受控实验没有证明足够迁移收益，生产实现继续使用 Chroma + SQL keyword + RRF。

当前开发基线仍不是新版安装包。正式 PostgreSQL 升级、真实 Windows Electron 启动/安装 E2E、真实 Vault 冲突/删除和版本发布继续单独验收。

## 2. 当前交付快照

| 范畴 | 状态 |
| --- | --- |
| 版本与发布 | `v1.3.0` 仍是唯一当前正式版本；tag、GitHub Release 和 Windows 安装资产保持不变。 |
| 统一检索 | `RetrievalRouter` 统一资料、笔记、概念、记忆与学习者状态；主聊天、ChatAgent、AgentKernel 和资料搜索均通过路由查询。 |
| 检索生命周期 | `retrieval_projections` 与 `retrieval_projection_chunks` 记录来源版本、配置指纹、状态、错误和分块；支持 ingest、refresh、forget、retry、rebuild 和用户隔离。 |
| 检索质量 | 16-case 固定质量集覆盖 Recall@5/10、MRR、NDCG、延迟、跨用户泄漏、删除残留、空查询和无 embedding 降级；hybrid Recall@5 为 `0.9833`。 |
| Qdrant 决策 | 真实 Qdrant Local 比较 dense+sparse+RRF、轻量词项重排和 sparse-only fallback；未满足明显优势门槛，不加入运行时依赖。 |
| 数据库 | SQLite lightweight migration 与 Alembic 当前 head 为 `20260822_10`；SQL 和原始文件始终是规范来源，向量只是可重建投影。 |
| 前端 | 资料侧栏展示单条资料投影状态、错误和重试操作；AI 设置展示 ready、degraded、failed 等用户范围统计。 |
| 本地回归 | 全后端 `387 passed, 8 skipped, 53 subtests passed`；新增资料 API 冒烟/隔离专项 `12 passed`；前端 `24 files / 74 tests passed`，桌面端 `21 passed`，前端构建和 lint 通过。 |
| 已通过 CI | PR #8 的 Backend、Frontend、PostgreSQL 16、多 worker 验收、Chromium、Windows smoke 和 Repository integrity 均已通过；Windows smoke 不等于真实 Electron 安装 E2E。 |

## 3. 已通过的远程验收

PR #8 于 2026-08-22 07:32 UTC 合入 `main@5da524c`。对应 [GitHub Actions run 32559668354](https://github.com/wlohf/Mnemox/actions/runs/32559668354) 中六个任务全部成功：

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
- 本轮新增 SQL 检索投影、更新/删除/重建生命周期、状态 UI、离线质量门禁与 Qdrant no-go；尚未单独创建新版 tag、安装包或 GitHub Release。

## 6. 下一阶段执行顺序

1. **概念图谱完整闭环**：资料候选概念与关系自动抽取、来源证据、人工确认、别名/改名/合并/拆分/删除、引用迁移和先修缺口下钻；SQL 是规范图来源。
2. **学习者状态与推荐决策**：统一强弱证据、计算遗忘风险与先修阻塞，生成可解释排序和推荐理由；真实 holdout 样本不足时保持 `collect_more_data`。
3. **SQL 时态记忆闭环**：处理冲突、替代、失效、人工纠错和派生删除，然后再判断 Graphiti Spike 是否必要。
4. **Coach 教学行为闭环**：按状态选择教学动作，保留草案确认，并记录 shown、accepted、rejected、started、completed、abandoned 与后续效果。
5. **AgentRuntime 纵向切片**：只在前述 Phase 1 数据、删除、回放和反馈边界稳定后，比较原生 AgentKernel 与 LangGraph。
6. **生产验收与版本发布**：完成正式 PostgreSQL 升级、真实 Windows Electron 启动/安装/升级 E2E、真实 Vault 冲突与删除、备份回滚、版本号、tag、Release 和安装包。

当前不进入多 Agent、语音、MCP 或其他生态扩展。
