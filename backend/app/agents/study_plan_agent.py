"""Study plan agent."""
from __future__ import annotations

from datetime import date

from sqlalchemy import func, select

from app.agents.base import BaseAgent
from app.models.goal import Goal, Task
from app.models.question import ReviewSchedule


class StudyPlanAgent(BaseAgent):
    name = "study_plan"
    description = "汇总目标、任务与复习压力，生成今日学习安排"

    async def run(self, payload: dict) -> dict:
        today = date.today()
        task_result = await self.context.db.execute(
            select(Task)
            .join(Goal, Task.goal_id == Goal.id)
            .where(
                Goal.user_id == self.context.user.id,
                Task.status != "completed",
                Task.planned_date <= today,
            )
            .order_by(Task.planned_date.asc(), Task.id.asc())
            .limit(10)
        )
        tasks = task_result.scalars().all()
        review_count_result = await self.context.db.execute(
            select(func.count(ReviewSchedule.id)).where(
                ReviewSchedule.user_id == self.context.user.id,
                ReviewSchedule.status == "pending",
                ReviewSchedule.scheduled_date <= today,
            )
        )
        due_reviews = int(review_count_result.scalar() or 0)
        plan_items = []
        if due_reviews:
            plan_items.append({"type": "review", "title": f"完成 {min(due_reviews, 8)} 个到期复习", "minutes": 25})
        for task in tasks[:4]:
            plan_items.append({"type": task.task_type or "task", "title": task.title, "task_id": task.id, "minutes": 25})
        if not plan_items:
            plan_items.append({"type": "reflection", "title": "做一次 10 分钟学习复盘，确定下一步输出", "minutes": 10})
        return {
            "date": today.isoformat(),
            "due_review_count": due_reviews,
            "pending_task_count": len(tasks),
            "items": plan_items,
        }
