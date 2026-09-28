# Learning API

## 职责

学习领域覆盖学习进度、目标/任务、每日计划、复习、学习会话和评估。

## Stable 前端边界

| 领域 | Service | 典型 endpoint |
| --- | --- | --- |
| 学习进度 | `learningApi.ts` | `/api/learning/...` |
| 目标/任务 | `goalApi.ts` | `/api/goals/...` |
| 日计划 | `planApi.ts` | `/api/plans/...` |
| 复习 | `reviewApi.ts` | `/api/review/...` |
| 学习会话 | `studySessionApi.ts` | `/api/study-sessions/...` |
| 画像 | `profileApi.ts` | `/api/profile`, `/api/profile/refresh` |

## 描述性行为证据（DI-0 首批）

`GET /api/profile/evidence?days=30` 是认证用户的只读证据接口，`days` 范围为 1～366；不接收查询其他用户的参数，不调用模型、不写记忆或画像。返回的 `assessment=descriptive_only` 明确这是记录汇总，尚不是用户特性或效果判断。

- `records`：当前规范 Pomodoro 的来源 ID/内容版本、发生/记录时间、同源组、结果、任务类型、实际/计划/历史原值、是否纳入与质量标记。关联任务/会话再次校验用户归属。每次读取重算，源记录变化/删除即时反映；不把 LearningEvent、摘要或报告重复算成另一段专注。
- `window` / `daily`：按专注结束时刻归入用户自然日；使用 CoachPreference 时区，配置缺失/无效则明确回退 UTC。未记录日期是 `no_observation`，实际时长为 `null`，不解释成没学习。跨午夜的一段专注整体归到结束日，尚不拆分活跃分钟。
- `metrics`：只汇总明确报告且通过质量检查的实际时长；中断前的实际学习也计入。没有有效时长时为 `null`；有部分有效时长时为已知部分之和，必须同时检查缺失条数。完成或提前完成比例仅描述记录结果；小时分布只代表结束记录数量。
- `coverage` / `quality_counts` / `limitations`：样本、覆盖天数、任务类型、同源组、缺失/异常及限制。Demo/模拟、未结束、未知时间基础、未来/倒序等记录退出汇总；合法长专注保留并提示复查，不直接当噪声删除。读取最多 5,000 条，截断必须显式提示。同源组数量不能证明统计独立。

历史 `duration` 可能是原计划，因此迁移不复制为 `actual_duration`，也不从墙上经过时间猜测活跃时长。新建计时保存 `planned_duration`，结束时只有明确提交实际值才写 `actual_duration`；原 `duration` 保留兼容。事件 `metadata.recorded_at` 为服务器接收时间，独立于发生时间，历史事件不补造此值。

旧离线批量导入的 `duration` 按该接口既有契约表示结束时报告的实际分钟，但缺少 `planned_duration` 不自动补成相同值。没有 `started_at` 时保留兼容存储所需的估算，来源标记 `offline_estimated`；证据返回 `estimated_start_time`，已知开始时间为 `null`，不能用估算的经过时间独立验证实际时长。

`/api/profile` 增加 `evidence_summary`（近 30 天）和 `lifetime_metrics`（最多读取 5,000 条的当前历史）；旧分数字段标记 deprecated。画像缓存遇旧契约、时区变化或自然日切换会重算，普通缓存仍有最多 1 小时有效期，可显式刷新。证据接口、聊天工具和 Coach 专注快照直接读取当前证据。画像扩展的 `undated_record_count`、`excluded_all_time_count`、`synthetic_all_time_count` 统计整个已读取集合，`quality_counts` 只属于当前窗口。

`/api/learning/dashboard` 增加 `time_zone`、可空 `today_actual_minutes`、`today_duration_unknown_count` 和 `evidence_quality`。兼容数值字段仍可能用 0 占位，新分析须读取可空值和缺失信息。Coach 快照对应使用 `learning.today_actual_minutes` 与 `learning.evidence_summary`。

当前任务上下文取自当前 Task，并非完整历史版本；来源版本是当前内容指纹，不是已保存的修订链。该接口不能用作“当时已知信息”的历史回放，也没有校准置信度。后续评测使用[案例格式](../evaluation/dynamic-understanding-case-template.md)，按时间保存输入快照和来源修订后才能验收历史重放。

兼容 EDA 报告已移除硬编码用户类型及人为置信度：`profile.confidence` 与 `summary.profile_confidence` 可空，当前返回 `null`；历史图表仍用旧口径，不能将其当作新证据评估输出。

## Goal Plan

`GoalPlanModal` 不再直接拼 HTTP 路由：

```text
GoalPlanModal
  -> listMaterialChapters()
  -> createGoalPlan() / createGoalTask()
  -> materialApi / goalApi
  -> apiClient
```

`createGoalPlan()` 和 `generateNextWeekGoalTasks()` 至少稳定暴露 `goal_id`、`generated_tasks`；其余任务明细以 OpenAPI 为准。

## Daily Plan

`listPlans(start, end)` 和 `savePlan(date, content)` 是页面与主 Layout 共用的 canonical 前端 Contract，避免多个页面各自拼 `/api/plans/...`。

## Review

`reviewApi.ts` 统一暴露任务列表、到期数量、内容生成、答案提交、完成和删除；页面只处理学习交互，不处理 HTTP 细节。


## 动态理解 API（DI-1 / DI-2）

全部 `/api/understanding` 路由要求当前用户登录，来源与模型配置始终按该用户核验。

| 方法/路径 | 用途 |
| --- | --- |
| GET `/api/understanding` | 三个独立开关、部署能力、有效经历数、估计、近期任务、图投影进度及 UTC 当天用量 |
| PUT `/api/understanding/preferences` | `analysis_enabled` / `graph_enabled` / `consume_enabled`，默认均 false |
| POST `/api/understanding/refresh` | 重读规范来源、确定性重评；图启用时也会排队增量抽取 |
| POST `/api/understanding/analyze` | `{request_id}` 幂等排队开放候选分析，202 返回现有 AgentJob |
| GET `/api/understanding/evidence/{id}` | 当前有效规范依据，附 graph 抽取状态/修订号；来源变更/删除、排除或跨账号均不可读 |
| DELETE `/api/understanding/evidence/{id}` | 从分析/图中移除并保留排除标记；原业务记录保留 |
| POST `/api/understanding/hypotheses/{id}/review` | `{version,action,correction?}`；action 为 correct/ignore/restore/withdraw/delete；过期版本 409 |
| GET `/api/understanding/hypotheses/{id}/history` | 修订及原因；失效来源的历史原文会清除 |
| GET `/api/understanding/memory?q=...` | 连续经历；返回 backend、reason、graph_attempted、graph_hits、graph_scope_truncated、experiences、timeline、connections；每条保留来源版本、retrieved_by 和 match_kind |
| POST `/api/understanding/graph/{rebuild\|reextract\|cleanup}` | `{request_id}` 幂等图操作；重新抽取需查询参数 `experience_id` 及正文 `experience_version`，版本不符返回 409；重建分批且不调用模型；图服务开启时允许在用户停用增强后清理 |
| POST `/api/understanding/jobs/{id}/retry` | `{request_id}` 幂等重试自己的失败任务，202；保留原调用账本及已完成阶段，非失败任务返回 409 |

`timeline` 是经历 ID/版本及时间字段的有序索引，不是模型生成的总结。`connections` 中共享实体只是检索线索，不声明身份、因果或永久事实。`graph_hits` 只计算本次返回中通过图命中且回 SQL 核验的来源；`graph_attempted=true` 不代表一定有有效命中。

`daily_usage` / 任务 `usage` 区分 `reported_tokens`、`actual_tokens`、`usage_missing_calls`、`reserved_tokens` 和 `configured_cost_usd`。实际用量不完整时 actual_tokens 为 null；任一调用缺少用量或单价时费用为 null。预算不足延迟，单次请求大于整个日预算则失败并返回 `understanding_call_exceeds_daily_budget`。

候选为 `unverified_hypothesis`。`support` / `counter` 引用原始证据；Coach 尝试信息通过 `context_refs` 引用，不增加独立支持。可操作化验证的 `interval_95` 是分组记录符合比例的近似区间，不能解释成判断真实概率。每日预算同时包含预留、成功、失败调用，预算不足延至下一 UTC 日。

计划 API 调整：`POST /api/plans/generate/{date}` 返回 `saved:false`、`generator:rules`、`base_version`；不覆盖计划。GET/list 增加 `version`，PUT 要求 `expected_version`（新计划为 0），冲突返回 409。关联真实任务的 Markdown 标记为 `<!-- task:ID:vVERSION -->`，保存前按账号和任务版本核验，不按标题猜测任务身份。

趋势、EDA、番茄钟统计的实际分钟和无观察时完成率可为 `null`；时段 `efficiency_score` 始终 `null`，`best_slot` 不再由人为分数推断。旧客户端需同时更新，避免把 null 显示为零。
