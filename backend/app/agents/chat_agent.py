"""Chat agent tools for read-only learning context lookup."""
from __future__ import annotations

import json

from sqlalchemy import or_, select
from sqlalchemy.orm import selectinload

from app.agents.base import AgentRunContext, AgentResult, BaseAgent
from app.models.goal import Goal, Task
from app.models.material import Material
from app.models.memory import UserMemory
from app.models.question import Question, WrongQuestion
from app.models.user_profile import UserProfile
from app.services.note_retriever import NoteRetriever
from app.services.retrieval_router import RetrievalRouter
from app.utils.utc import utc_now_db, utc_today

CONFIRMED_REVIEW_STATUS = "confirmed"


class ChatAgent(BaseAgent):
    name = "chat"
    display_name = "ChatAgent"
    description = "为对话提供受控 tool-calling 查询笔记、资料和错题"

    async def run(self, ctx: AgentRunContext) -> AgentResult:
        tool = str(ctx.payload.get("tool") or ctx.task or "").strip()
        query = str(ctx.payload.get("query") or "").strip()
        limit = int(ctx.payload.get("limit") or 5)
        data = await self.call_tool(ctx, tool=tool, query=query, limit=limit)
        return AgentResult(
            agent=self.name,
            task=tool or "tool_call",
            status="completed",
            summary=f"工具 {tool or 'unknown'} 返回 {len(data.get('items', []))} 条结果。",
            actions=[],
            data=data,
        )

    async def call_tool(self, ctx: AgentRunContext, tool: str, query: str, limit: int = 5) -> dict:
        limit = max(1, min(10, int(limit or 5)))
        if tool == "search_notes":
            return await self._search_notes(ctx, query, limit)
        if tool == "search_materials":
            return await self._search_materials(ctx, query, limit)
        if tool == "search_wrong_questions":
            return await self._search_wrong_questions(ctx, query, limit)
        if tool == "search_memories":
            return await self._search_memories(ctx, query, limit)
        if tool == "search_concepts":
            return await self._search_concepts(ctx, query, limit)
        if tool == "search_learner_state":
            return await self._search_learner_state(ctx, query, limit)
        if tool == "get_profile":
            return await self._get_profile(ctx)
        if tool == "get_agent_learning_profile":
            return await self._get_agent_learning_profile(ctx)
        if tool == "get_today_tasks":
            return await self._get_today_tasks(ctx, limit)
        if tool == "get_recent_feedback":
            return await self._get_recent_feedback(ctx, limit)
        return {"tool": tool, "items": [], "error": "unsupported_tool"}

    async def _router_search(
        self,
        ctx: AgentRunContext,
        query: str,
        limit: int,
        *,
        tool: str,
        source_type: str,
        route: str,
    ) -> dict:
        hits = await RetrievalRouter(ctx.db).search(
            query,
            user_id=ctx.user_id,
            source_types=(source_type,),
            top_k=limit,
        )
        items = []
        for hit in hits:
            item = hit.to_dict()
            item.update(
                {
                    "id": hit.source_id,
                    "title": hit.title,
                    "content_preview": hit.excerpt[:240],
                    "route": route,
                }
            )
            if source_type == "memory":
                item.update(
                    {
                        "key": hit.title,
                        "value_preview": hit.excerpt[:240],
                        "locked": hit.metadata.get("locked"),
                        "memory_key": hit.title,
                        "memory_value": hit.excerpt,
                        "category": hit.metadata.get("category"),
                        "confidence": hit.metadata.get("confidence"),
                        "is_locked": hit.metadata.get("locked"),
                        "review_status": hit.metadata.get("review_status"),
                    }
                )
            items.append(item)
        return {"tool": tool, "query": query, "items": items}

    async def _search_notes(self, ctx: AgentRunContext, query: str, limit: int) -> dict:
        return await self._router_search(
            ctx, query, limit, tool="search_notes", source_type="note", route="/notes"
        )

    async def _search_materials(self, ctx: AgentRunContext, query: str, limit: int) -> dict:
        return await self._router_search(
            ctx, query, limit, tool="search_materials", source_type="material", route="/materials"
        )

    async def _search_wrong_questions(self, ctx: AgentRunContext, query: str, limit: int) -> dict:
        stmt = select(WrongQuestion).options(selectinload(WrongQuestion.question).selectinload(Question.chapter)).where(WrongQuestion.user_id == ctx.user_id)
        if query:
            like = f"%{query}%"
            stmt = stmt.join(Question, WrongQuestion.question_id == Question.id).where(or_(WrongQuestion.knowledge_point.ilike(like), Question.content.ilike(like)))
        result = await ctx.db.execute(stmt.order_by(WrongQuestion.last_wrong_at.desc(), WrongQuestion.id.desc()).limit(limit))
        items = []
        for item in result.scalars().all():
            question = item.__dict__.get("question")
            items.append({"id": item.id, "knowledge_point": item.knowledge_point, "content_preview": ((question.content if question else "") or "")[:240], "mastery_status": item.mastery_status, "route": "/wrong-questions"})
        return {"tool": "search_wrong_questions", "query": query, "items": items}

    async def _search_memories(self, ctx: AgentRunContext, query: str, limit: int) -> dict:
        return await self._router_search(
            ctx, query, limit, tool="search_memories", source_type="memory", route="/agent"
        )

    async def _search_concepts(self, ctx: AgentRunContext, query: str, limit: int) -> dict:
        return await self._router_search(
            ctx, query, limit, tool="search_concepts", source_type="concept", route="/knowledge-graph"
        )

    async def _search_learner_state(self, ctx: AgentRunContext, query: str, limit: int) -> dict:
        return await self._router_search(
            ctx,
            query,
            limit,
            tool="search_learner_state",
            source_type="learner_state",
            route="/agent",
        )

    async def _get_profile(self, ctx: AgentRunContext) -> dict:
        result = await ctx.db.execute(select(UserProfile).where(UserProfile.user_id == ctx.user_id))
        profile = result.scalar_one_or_none()
        if not profile:
            return {"tool": "get_profile", "profile": None}
        return {
            "tool": "get_profile",
            "profile": {
                "total_study_hours": profile.total_study_hours,
                "total_pomodoros": profile.total_pomodoros,
                "focus_score": profile.focus_score,
                "consistency_score": profile.consistency_score,
                "planning_score": profile.planning_score,
                "self_control_score": profile.self_control_score,
                "optimal_hours": profile.optimal_hours,
                "preferred_time_slots": profile.preferred_time_slots,
                "weak_points": profile.weak_points,
                "coaching_suggestions": profile.coaching_suggestions,
            },
        }

    async def _get_agent_learning_profile(self, ctx: AgentRunContext) -> dict:
        result = await ctx.db.execute(
            select(UserMemory).where(
                UserMemory.user_id == ctx.user_id,
                UserMemory.memory_key == "agent_learning_profile",
                UserMemory.status == "active",
                UserMemory.review_status == CONFIRMED_REVIEW_STATUS,
                or_(UserMemory.expires_at.is_(None), UserMemory.expires_at > utc_now_db()),
            )
        )
        item = result.scalar_one_or_none()
        data = None
        if item:
            try:
                data = json.loads(item.memory_value or "{}")
            except Exception:
                data = {"raw": item.memory_value}
        return {"tool": "get_agent_learning_profile", "profile": data}

    async def _get_recent_feedback(self, ctx: AgentRunContext, limit: int) -> dict:
        result = await ctx.db.execute(
            select(UserMemory)
            .where(
                UserMemory.user_id == ctx.user_id,
                UserMemory.status == "active",
                UserMemory.review_status == CONFIRMED_REVIEW_STATUS,
                or_(UserMemory.expires_at.is_(None), UserMemory.expires_at > utc_now_db()),
                UserMemory.category == "agent_feedback",
            )
            .order_by(UserMemory.last_seen_at.desc(), UserMemory.id.desc())
            .limit(limit)
        )
        items = []
        for row in result.scalars().all():
            try:
                data = json.loads(row.memory_value or "{}")
            except Exception:
                data = {"raw": row.memory_value}
            items.append({
                "id": row.id,
                "action_id": data.get("action_id"),
                "action_type": data.get("action_type"),
                "outcome": data.get("outcome"),
                "reason_code": data.get("reason_code"),
                "notes": data.get("notes"),
                "recorded_at": data.get("recorded_at"),
            })
        return {"tool": "get_recent_feedback", "items": items}

    async def _get_today_tasks(self, ctx: AgentRunContext, limit: int) -> dict:
        today = utc_today()
        result = await ctx.db.execute(
            select(Task)
            .join(Goal, Task.goal_id == Goal.id)
            .where(Goal.user_id == ctx.user_id, Task.planned_date == today)
            .order_by(Task.status.asc(), Task.id.desc())
            .limit(limit)
        )
        return {"tool": "get_today_tasks", "date": today.isoformat(), "items": [
            {"id": task.id, "goal_id": task.goal_id, "title": task.title, "status": task.status, "task_type": task.task_type, "route": "/goals"}
            for task in result.scalars().all()
        ]}
