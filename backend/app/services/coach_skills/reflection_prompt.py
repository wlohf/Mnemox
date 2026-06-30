"""Post-session reflection prompt skill."""
from __future__ import annotations

from app.services.coach_skills.base import CoachSkill, CoachSkillContext, CoachSkillResult, explain_with_context, trim_text


class ReflectionPromptSkill(CoachSkill):
    id = "reflection_prompt"
    display_name = "短反思提示"
    description = "在有意义的专注或学习后，提示用户做一次很短的反思。"
    trigger_event_types = {"pomodoro.completed", "session.meaningful_completed"}
    required_context = {"learning", "tasks", "daily_plan"}
    tone_rules = ["简短", "只问一个问题", "不打断低价值会话"]
    safety_rules = ["只提示反思", "不自动写入计划或笔记"]

    async def generate(self, ctx: CoachSkillContext) -> CoachSkillResult:
        payload = ctx.event.get("payload") or {}
        task_name = trim_text(payload.get("task_name") or payload.get("task") or "", 34)
        if task_name:
            body = f"刚完成「{task_name}」。用1句话写下：这个任务里最卡的一点是什么？"
        else:
            body = "刚完成一次专注。用1句话写下：刚才最卡的一点是什么？"
        return CoachSkillResult(
            title="做1句反思",
            body=body,
            suggested_action={"type": "ask_reflection", "label": "去写复盘", "route": "/plans"},
            route="/plans",
            explainability=explain_with_context(
                ctx,
                "完成专注后做短反思，能把学习行为转成可复用记忆。",
                [f"today_completed_pomodoros={(ctx.snapshot.get('learning') or {}).get('today_completed_pomodoros', 0)}"],
            ),
        )
