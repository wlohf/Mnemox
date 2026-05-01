"""Chat agent tools for read-only learning context lookup."""
from __future__ import annotations

import json
from datetime import date

from sqlalchemy import or_, select
from sqlalchemy.orm import selectinload

from app.agents.base import AgentRunContext, AgentResult, BaseAgent
from app.models.goal import Goal, Task
from app.models.material import Material
from app.models.memory import UserMemory
from app.models.note import Note
from app.models.question import Question, WrongQuestion
from app.models.user_profile import UserProfile


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
        if tool == "get_profile":
            return await self._get_profile(ctx)
        if tool == "get_agent_learning_profile":
            return await self._get_agent_learning_profile(ctx)
        if tool == "get_today_tasks":
            return await self._get_today_tasks(ctx, limit)
        if tool == "get_recent_feedback":
            return await self._get_recent_feedback(ctx, limit)
        return {"tool": tool, "items": [], "error": "unsupported_tool"}

    async def _search_notes(self, ctx: AgentRunContext, query: str, limit: int) -> dict:
        stmt = select(Note).where(Note.user_id == ctx.user_id)
        if query:
            like = f"%{query}%"
            stmt = stmt.where(or_(Note.title.ilike(like), Note.content.ilike(like), Note.tags.ilike(like)))
        result = await ctx.db.execute(stmt.order_by(Note.updated_at.desc(), Note.id.desc()).limit(limit))
        return {"tool": "search_notes", "query": query, "items": [
            {"id": note.id, "title": note.title, "content_preview": (note.content or "")[:240], "route": "/notes"}
            for note in result.scalars().all()
        ]}

    async def _search_materials(self, ctx: AgentRunContext, query: str, limit: int) -> dict:
        stmt = select(Material).where(Material.user_id == ctx.user_id)
        if query:
            like = f"%{query}%"
            stmt = stmt.where(or_(Material.title.ilike(like), Material.content.ilike(like)))
        result = await ctx.db.execute(stmt.order_by(Material.updated_at.desc(), Material.id.desc()).limit(limit))
        return {"tool": "search_materials", "query": query, "items": [
            {"id": material.id, "title": material.title, "content_preview": (material.content or "")[:240], "route": "/materials"}
            for material in result.scalars().all()
        ]}

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
        stmt = select(UserMemory).where(UserMemory.user_id == ctx.user_id, UserMemory.status == "active")
        if query:
            like = f"%{query}%"
            stmt = stmt.where(or_(UserMemory.memory_key.ilike(like), UserMemory.memory_value.ilike(like), UserMemory.category.ilike(like)))
        result = await ctx.db.execute(stmt.order_by(UserMemory.last_seen_at.desc(), UserMemory.id.desc()).limit(limit))
        return {"tool": "search_memories", "query": query, "items": [
            {"id": item.id, "key": item.memory_key, "category": item.category, "value_preview": (item.memory_value or "")[:240], "confidence": item.confidence, "locked": bool(item.is_locked)}
            for item in result.scalars().all()
        ]}

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
            .where(UserMemory.user_id == ctx.user_id, UserMemory.status == "active", UserMemory.category == "agent_feedback")
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
        today = date.today()
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
