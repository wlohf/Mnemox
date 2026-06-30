"""Minimum next step skill."""
from __future__ import annotations

from app.services.coach_skills.base import CoachSkill, CoachSkillContext, CoachSkillResult, explain_with_context, trim_text


class MinimumNextStepSkill(CoachSkill):
    id = "minimum_next_step"
    display_name = "最小下一步"
    description = "把任务过载、卡住、无从开始转成一个具体动作。"
    trigger_event_types = {"chat.overload_detected", "task.overdue", "app.inactive_returned"}
    required_context = {"tasks", "review", "learning"}
    tone_rules = ["只给一个动作", "动作要能立即开始", "避免完整计划"]
    safety_rules = ["不直接创建任务", "不修改计划"]

    async def generate(self, ctx: CoachSkillContext) -> CoachSkillResult:
        tasks = ctx.snapshot.get("tasks") or {}
        review = ctx.snapshot.get("review") or {}
        due_count = int(review.get("due_review_count") or 0)
        overdue = tasks.get("overdue_tasks") or []
        today_tasks = tasks.get("today_tasks") or []

        if due_count > 0:
            body = "下一步只做一件事：打开复习页，完成最旧的1条。不要先整理全部任务。"
            action = {"type": "open_route", "label": "做1条复习", "route": "/review"}
            signals = [f"到期复习 {due_count} 条"]
        elif overdue:
            title = trim_text(overdue[0].get("title"), 34)
            body = f"先不要补全部过期任务。只把「{title}」缩成10分钟，完成一个开头。"
            action = {"type": "start_focus", "label": "10分钟开头", "route": "/pomodoro", "minutes": 10}
            signals = [f"过期任务 {len(overdue)} 个"]
        elif today_tasks:
            title = trim_text(today_tasks[0].get("title"), 34)
            body = f"下一步只做「{title}」的第一小段。开10分钟番茄钟，结束后再决定是否继续。"
            action = {"type": "start_focus", "label": "10分钟开始", "route": "/pomodoro", "minutes": 10}
            signals = ["有今日任务"]
        else:
            body = "下一步：写下一句“我现在要学什么”，然后开10分钟番茄钟。先启动，不整理系统。"
            action = {"type": "start_focus", "label": "10分钟启动", "route": "/pomodoro", "minutes": 10}
            signals = ["无明确任务"]

        return CoachSkillResult(
            title="只做下一步",
            body=body,
            suggested_action=action,
            route=action.get("route"),
            explainability=explain_with_context(ctx, "检测到过载或无从开始，Coach 将范围压缩到一个动作。", signals),
        )
