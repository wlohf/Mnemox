"""Planning rescue skill."""
from __future__ import annotations

from app.services.coach_skills.base import CoachSkill, CoachSkillContext, CoachSkillResult, explain_with_context, trim_text


class PlanningRescueSkill(CoachSkill):
    id = "planning_rescue"
    display_name = "计划救援"
    description = "当天计划缺失或崩掉时，生成一个确认优先的轻量计划草案。"
    trigger_event_types = {"plan.day_started_without_plan", "plan.collapsed", "chat.overload_detected"}
    required_context = {"tasks", "daily_plan", "review"}
    tone_rules = ["只给今天最少项", "避免长计划", "优先处理复习与一个核心任务"]
    safety_rules = ["只生成草案", "加入每日计划前必须确认"]

    async def generate(self, ctx: CoachSkillContext) -> CoachSkillResult:
        tasks = ctx.snapshot.get("tasks") or {}
        review = ctx.snapshot.get("review") or {}
        today = str(ctx.snapshot.get("date") or "")
        due_count = int(review.get("due_review_count") or 0)
        today_tasks = tasks.get("today_tasks") or []

        items: list[dict[str, str]] = []
        if due_count > 0:
            items.append({"title": "清理最旧的3条到期复习", "task_type": "review"})
        if today_tasks:
            items.append({"title": trim_text(today_tasks[0].get("title"), 80), "task_type": today_tasks[0].get("task_type") or "learn"})
        if not items:
            items.append({"title": "10分钟启动：写下今天要学的一个知识点", "task_type": "learn"})

        return CoachSkillResult(
            title="生成最小计划",
            body="今天先别排满。Coach 准备了一个最多2项的计划草案，确认后再加入每日计划。",
            suggested_action={"type": "create_daily_plan_draft", "label": "查看草案", "route": "/plans"},
            route="/plans",
            requires_confirmation=True,
            draft={"intent": "add_daily_plan_items", "date": today, "items": [{"planned_date": today, **item} for item in items[:2]]},
            explainability=explain_with_context(
                ctx,
                "检测到今日计划缺失或任务过载，先压缩到最小可执行计划。",
                [f"due_review_count={due_count}", f"today_tasks={len(today_tasks)}"],
            ),
        )
