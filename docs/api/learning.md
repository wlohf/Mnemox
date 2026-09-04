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