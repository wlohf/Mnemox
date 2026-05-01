"""Study plan agent: generate small daily actions from existing goals/tasks."""
from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import func, select

from app.agents.base import AgentRunContext, AgentResult, BaseAgent
from app.models.goal import Goal, Task
from app.models.question import ReviewSchedule, WrongQuestion


class StudyPlanAgent(BaseAgent):
    name = "study_plan"
    display_name = "StudyPlanAgent"
    description = "根据目标、任务、错题和复习状态生成或调整每日计划"

    async def run(self, ctx: AgentRunContext) -> AgentResult:
        today = date.today()
        db = ctx.db
        goals_result = await db.execute(
            select(Goal)
            .where(Goal.user_id == ctx.user_id, Goal.status == "active")
            .order_by(Goal.deadline.is_(None), Goal.deadline, Goal.id)
            .limit(5)
        )
        goals = list(goals_result.scalars().all())
        today_tasks_result = await db.execute(
            select(Task)
            .join(Goal, Task.goal_id == Goal.id)
            .where(Goal.user_id == ctx.user_id, Task.planned_date == today)
            .order_by(Task.id)
        )
        today_tasks = list(today_tasks_result.scalars().all())
        weak_result = await db.execute(
            select(WrongQuestion.knowledge_point, func.count(WrongQuestion.id).label("cnt"))
            .where(WrongQuestion.user_id == ctx.user_id, WrongQuestion.knowledge_point.is_not(None))
            .group_by(WrongQuestion.knowledge_point)
            .order_by(func.count(WrongQuestion.id).desc())
            .limit(3)
        )
        weak_points = [{"name": str(name), "count": int(cnt)} for name, cnt in weak_result.all() if name]
        due_review_count = int(await db.scalar(select(func.count(ReviewSchedule.id)).where(
            ReviewSchedule.user_id == ctx.user_id,
            ReviewSchedule.status == "pending",
            ReviewSchedule.scheduled_date <= func.now(),
            ReviewSchedule.is_archived.is_(False),
        )) or 0)
        actions: list[dict[str, Any]] = []
        created_task: dict[str, Any] | None = None
        if not goals:
            actions.append({"type": "navigate", "route": "/goals", "title": "先创建一个学习目标"})
            summary = "未发现活跃目标，建议先创建目标。"
        elif today_tasks:
            actions.append({"type": "navigate", "route": "/pomodoro", "title": f"开始今日任务：{today_tasks[0].title}"})
            summary = f"今天已有 {len(today_tasks)} 个任务，建议直接进入专注执行。"
        else:
            goal = goals[0]
            description = "StudyPlanAgent 自动生成：用 25 分钟完成一个可交付的小切片，并记录卡点。"
            if weak_points:
                description += f" 优先关注薄弱点：{weak_points[0]['name']}。"
            if due_review_count:
                description += f" 今日另有 {due_review_count} 条到期复习，建议任务后清理。"
            task = Task(
                goal_id=goal.id,
                title=f"完成《{goal.title}》的今日最小行动"[:200],
                description=description,
                task_type="learn",
                planned_date=today,
                status="pending",
            )
            db.add(task)
            await db.flush()
            created_task = {"id": task.id, "goal_id": task.goal_id, "title": task.title, "planned_date": today.isoformat(), "route": "/plans"}
            actions.append({"type": "create_task", "task": created_task})
            summary = "已为当前目标生成今日最小行动任务。"
        return AgentResult(
            agent=self.name,
            task=ctx.task,
            status="completed",
            summary=summary,
            actions=actions,
            data={"active_goal_count": len(goals), "today_task_count": len(today_tasks), "weak_points": weak_points, "due_review_count": due_review_count, "created_task": created_task},
        )
