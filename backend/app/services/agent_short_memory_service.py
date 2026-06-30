"""Per-request short memory assembly for the Agent."""
from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.memory import ConversationSummary
from app.services.goal_context_service import build_goal_context
from app.services.learning_event_service import list_recent_learning_events


def _json_loads(value: str | None, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except Exception:
        return fallback


def _summary_to_dict(row: ConversationSummary | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "conversation_id": row.conversation_id,
        "summary": row.summary or "",
        "key_points": _json_loads(row.key_points, []),
        "todo_items": _json_loads(row.todo_items, []),
        "questions_asked": _json_loads(row.questions_asked, []),
        "confusions": _json_loads(row.confusions, []),
        "misconceptions": _json_loads(row.misconceptions, []),
        "review_prompts": _json_loads(row.review_prompts, []),
        "message_count": row.message_count or 0,
        "last_message_at": row.last_message_at.isoformat() if row.last_message_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _temporary_preferences_from_query(query: str) -> list[str]:
    text = (query or "").strip()
    if not text:
        return []
    preferences: list[str] = []
    negative_write_patterns = [
        ("先不要", "本轮用户要求先不要执行写入，只讨论方案。"),
        ("不要创建", "本轮用户明确不想创建新任务/目标/笔记。"),
        ("别创建", "本轮用户明确不想创建新任务/目标/笔记。"),
        ("只讨论", "本轮用户希望只讨论，不直接生成可执行写入。"),
        ("先聊", "本轮用户希望先沟通方案，再决定是否执行。"),
    ]
    for marker, preference in negative_write_patterns:
        if marker in text and preference not in preferences:
            preferences.append(preference)
    if re.search(r"(简单|短一点|简短|别太长)", text):
        preferences.append("本轮用户偏好简短回答和小步行动。")
    if re.search(r"(详细|展开|一步步|完整)", text):
        preferences.append("本轮用户希望获得更完整的推理和步骤。")
    return preferences[:5]


async def _get_conversation_summary(
    db: AsyncSession,
    user_id: int,
    conversation_id: int | None,
) -> dict[str, Any] | None:
    if conversation_id is None:
        return None
    result = await db.execute(
        select(ConversationSummary)
        .where(ConversationSummary.user_id == user_id, ConversationSummary.conversation_id == conversation_id)
        .order_by(ConversationSummary.updated_at.desc(), ConversationSummary.id.desc())
        .limit(1)
    )
    return _summary_to_dict(result.scalar_one_or_none())


async def build_short_memory(
    db: AsyncSession,
    user_id: int,
    *,
    conversation_id: int | None = None,
    goal_id: int | None = None,
    query: str = "",
    now: datetime | None = None,
) -> dict[str, Any]:
    """Assemble volatile Agent context without writing durable user beliefs."""

    current = now or datetime.now()
    conversation_summary = await _get_conversation_summary(db, user_id, conversation_id)
    recent_events = await list_recent_learning_events(db, user_id, limit=30)
    active_goal_context = await build_goal_context(db, user_id, goal_id=goal_id, now=current)

    return {
        "user_id": user_id,
        "generated_at": current.isoformat(),
        "conversation_id": conversation_id,
        "conversation_summary": conversation_summary,
        "recent_events": recent_events,
        "active_goal_context": {
            "active_goal": active_goal_context.get("active_goal"),
            "today_focus": active_goal_context.get("today_focus"),
            "risk_flags": active_goal_context.get("risk_flags"),
            "evidence": active_goal_context.get("evidence", []),
            "supporting_context": active_goal_context.get("supporting_context", {}),
        },
        "current_surface": None,
        "temporary_preferences": _temporary_preferences_from_query(query),
    }
