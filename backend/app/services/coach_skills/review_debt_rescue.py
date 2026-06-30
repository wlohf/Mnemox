"""Review debt rescue skill."""
from __future__ import annotations

from app.services.coach_skills.base import CoachSkill, CoachSkillContext, CoachSkillResult, explain_with_context, trim_text


class ReviewDebtRescueSkill(CoachSkill):
    id = "review_debt_rescue"
    display_name = "复习积压救援"
    description = "到期复习过多时，建议只清理最旧的少量项目。"
    trigger_event_types = {"review.debt_high"}
    required_context = {"review"}
    tone_rules = ["降低负担", "先处理最旧项目", "数量小而明确"]
    safety_rules = ["不自动修改复习计划", "不声称已完成复习"]

    async def generate(self, ctx: CoachSkillContext) -> CoachSkillResult:
        review = ctx.snapshot.get("review") or {}
        due_count = int(review.get("due_review_count") or 0)
        items = review.get("due_review_items") or []
        first = trim_text((items[0] or {}).get("title") if items else "", 32)
        if first:
            body = f"现在有{due_count}条到期复习。别一次清空，先做最旧的3条，从「{first}」开始。"
        else:
            body = f"现在有{due_count}条到期复习。先做最旧的3条，目标是减压，不是一次清空。"

        return CoachSkillResult(
            title="先清3条复习",
            body=body,
            suggested_action={
                "type": "open_route",
                "label": "开始复习",
                "route": "/review",
            },
            route="/review",
            explainability=explain_with_context(ctx, "到期复习数量超过阈值，优先做最旧少量项目。", [f"due_review_count={due_count}"]),
        )
