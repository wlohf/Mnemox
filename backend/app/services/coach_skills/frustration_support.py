"""Frustration and discouragement support skill."""
from __future__ import annotations

from app.services.coach_skills.base import CoachSkill, CoachSkillContext, CoachSkillResult, explain_with_context, trim_text


class FrustrationSupportSkill(CoachSkill):
    id = "frustration_support"
    display_name = "挫败支持"
    description = "用户表达沮丧、自我否定、烦躁或反复失败时，先稳定状态，再给一个可完成动作。"
    trigger_event_types = {"chat.frustration_detected"}
    required_context = {"tasks", "review", "memory"}
    tone_rules = ["先承认感受", "不说教", "不把情绪问题立即转成大计划", "任务缩小到可完成"]
    safety_rules = ["不提供临床心理治疗建议", "危机表达时优先建议寻求现实支持", "不编造用户历史"]

    async def generate(self, ctx: CoachSkillContext) -> CoachSkillResult:
        payload = ctx.event.get("payload") or {}
        text = str(payload.get("text") or payload.get("message") or "")
        if any(word in text for word in ["自杀", "不想活", "伤害自己", "结束生命", "suicide", "self-harm"]):
            return CoachSkillResult(
                title="先保证安全",
                body="这已经不是学习效率问题了。请先联系身边可信的人，或当地紧急求助渠道；现在不要独自硬扛。",
                suggested_action={"type": "ask_support", "label": "联系现实支持", "route": "/"},
                route="/",
                explainability=explain_with_context(ctx, "文本出现危机信号，Coach 暂停学习优化建议。", ["crisis_language_detected"]),
            )

        tasks = ctx.snapshot.get("tasks") or {}
        review = ctx.snapshot.get("review") or {}
        today_tasks = tasks.get("today_tasks") or []
        due_count = int(review.get("due_review_count") or 0)
        if due_count > 0:
            body = "这种挫败感先别用意志力顶。只做1条最旧复习，做完就停，用一次完成感把状态拉回来。"
            action = {"type": "open_route", "label": "做1条复习", "route": "/review"}
            signals = [f"到期复习 {due_count} 条"]
        elif today_tasks:
            title = trim_text(today_tasks[0].get("title"), 28)
            body = f"你现在不是不行，是任务需要变小。先把「{title}」切成5分钟，只写第一步。"
            action = {"type": "start_focus", "label": "5分钟重启", "route": "/pomodoro", "minutes": 5}
            signals = ["有今日待办"]
        else:
            body = "先别评价自己。做一个5分钟重启：打开番茄钟，只整理桌面或写下一句要学什么。"
            action = {"type": "start_focus", "label": "5分钟重启", "route": "/pomodoro", "minutes": 5}
            signals = ["无明确待办"]

        return CoachSkillResult(
            title="先降难度",
            body=body,
            suggested_action=action,
            route=action.get("route"),
            explainability=explain_with_context(ctx, "你表达了挫败或自我否定，Coach 优先降低任务难度。", signals),
        )
