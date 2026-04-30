"""Review planning agent."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import select

from app.agents.base import BaseAgent
from app.models.question import WrongQuestion


class ReviewAgent(BaseAgent):
    name = "review"
    description = "根据到期错题与掌握度生成复习建议"

    async def run(self, payload: dict) -> dict:
        limit = int(payload.get("limit") or 8)
        now = datetime.now()
        result = await self.context.db.execute(
            select(WrongQuestion)
            .where(
                WrongQuestion.user_id == self.context.user.id,
                WrongQuestion.next_review_at.isnot(None),
                WrongQuestion.next_review_at <= now,
            )
            .order_by(WrongQuestion.next_review_at.asc())
            .limit(max(1, min(limit, 20)))
        )
        due = result.scalars().all()
        items = [
            {
                "wrong_question_id": item.id,
                "knowledge_point": item.knowledge_point,
                "mastery_status": item.mastery_status,
                "mastery_score": item.mastery_score,
                "next_review_at": item.next_review_at.isoformat() if item.next_review_at else None,
            }
            for item in due
        ]
        if not items:
            return {
                "summary": "当前没有到期错题。建议用 10 分钟回顾最近笔记，并补一道主动回忆题。",
                "items": [],
                "actions": ["回顾今日笔记", "补充一道自测题", "整理一个易错知识点"],
            }
        actions = ["先复习 mastery_score 最低的错题", "答完后立即标记回忆难度", "把仍然卡住的题转成笔记或 Anki 卡片"]
        return {
            "summary": f"当前有 {len(items)} 道到期错题，建议按掌握度从低到高复习。",
            "items": items,
            "actions": actions,
        }
