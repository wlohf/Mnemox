"""Review agent: organize due Anki cards and wrong-question review schedules."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import select

from app.agents.base import AgentRunContext, AgentResult, BaseAgent
from app.models.anki import AnkiCard
from app.models.question import ReviewSchedule, WrongQuestion


class ReviewAgent(BaseAgent):
    name = "review"
    display_name = "ReviewAgent"
    description = "基于简化遗忘曲线调度 Anki 卡片和错题复习"

    async def run(self, ctx: AgentRunContext) -> AgentResult:
        now = datetime.now()
        db = ctx.db
        anki_result = await db.execute(
            select(AnkiCard)
            .where(AnkiCard.user_id == ctx.user_id, AnkiCard.due_at <= now)
            .order_by(AnkiCard.due_at.asc(), AnkiCard.id.asc())
            .limit(20)
        )
        due_anki = list(anki_result.scalars().all())
        wrong_result = await db.execute(
            select(WrongQuestion)
            .where(
                WrongQuestion.user_id == ctx.user_id,
                WrongQuestion.next_review_at.is_not(None),
                WrongQuestion.next_review_at <= now,
            )
            .order_by(WrongQuestion.next_review_at.asc(), WrongQuestion.id.asc())
            .limit(50)
        )
        due_wrong = list(wrong_result.scalars().all())
        created_schedules = 0
        for item in due_wrong:
            existing = await db.scalar(
                select(ReviewSchedule.id).where(
                    ReviewSchedule.user_id == ctx.user_id,
                    ReviewSchedule.item_type == "question",
                    ReviewSchedule.item_id == item.id,
                    ReviewSchedule.status == "pending",
                    ReviewSchedule.is_archived.is_(False),
                )
            )
            if existing:
                continue
            db.add(ReviewSchedule(
                user_id=ctx.user_id,
                item_type="question",
                item_id=item.id,
                scheduled_date=item.next_review_at or now,
                interval_days=1,
                ease_factor=250,
                repetitions=item.review_count or 0,
                status="pending",
            ))
            created_schedules += 1
        if created_schedules:
            await db.flush()
        actions = []
        if due_wrong:
            actions.append({"type": "navigate", "route": "/review", "title": f"复习 {len(due_wrong)} 条到期错题"})
        if due_anki:
            actions.append({"type": "navigate", "route": "/anki", "title": f"复习 {len(due_anki)} 张 Anki 卡片"})
        if not actions:
            actions.append({"type": "navigate", "route": "/anki", "title": "暂无积压，创建或生成新卡片"})
        return AgentResult(
            agent=self.name,
            task=ctx.task,
            status="completed",
            summary=f"发现 {len(due_anki)} 张到期 Anki 卡片、{len(due_wrong)} 条到期错题，补齐 {created_schedules} 条复习计划。",
            actions=actions,
            data={"due_anki_count": len(due_anki), "due_wrong_question_count": len(due_wrong), "created_review_schedules": created_schedules},
        )
