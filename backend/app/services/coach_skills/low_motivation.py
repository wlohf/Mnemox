"""Low motivation coaching skill."""
from __future__ import annotations

from app.services.coach_skills.base import CoachSkill, CoachSkillContext, CoachSkillResult, explain_with_context, trim_text


class LowMotivationSkill(CoachSkill):
    id = "low_motivation"
    display_name = "低动力支持"
    description = "用户表达学不进去、没动力或难以继续时，给一个很小的下一步。"
    trigger_event_types = {"chat.low_motivation_detected", "chat.frustration_detected"}
    required_context = {"tasks", "review", "daily_plan", "memory"}
    tone_rules = ["一句承认状态", "避免说教", "只给一个最小动作"]
    safety_rules = ["不提供临床心理建议", "不编造用户历史"]

    async def generate(self, ctx: CoachSkillContext) -> CoachSkillResult:
        tasks = ctx.snapshot.get("tasks") or {}
        review = ctx.snapshot.get("review") or {}
        due_count = int(review.get("due_review_count") or 0)
        today_tasks = tasks.get("today_tasks") or []

        if due_count > 0:
            action = {
                "type": "open_route",
                "label": "先做1条复习",
                "route": "/review",
            }
            body = "学不进去时先别硬扛，打开复习页只做最旧的1条，做完就停也可以。"
            signals = [f"到期复习 {due_count} 条"]
        elif today_tasks:
            task = today_tasks[0]
            action = {
                "type": "start_focus",
                "label": "10分钟启动",
                "route": "/pomodoro",
                "task_id": task.get("id"),
            }
            body = f"现在先不规划，给「{trim_text(task.get('title'), 28)}」做10分钟启动，目标只是坐下来。"
            signals = ["有今日待办"]
        else:
            action = {
                "type": "start_focus",
                "label": "打开番茄钟",
                "route": "/pomodoro",
            }
            body = "状态低的时候，把目标降到10分钟：打开番茄钟，只做一个能开始的动作。"
            signals = ["无明确今日任务"]

        return CoachSkillResult(
            title="先做最小一步",
            body=body,
            suggested_action=action,
            route=action.get("route"),
            explainability=explain_with_context(ctx, "你表达了低动力或难以开始，Coach 只给一个小动作。", signals),
        )
