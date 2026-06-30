"""Normalized learning event recording for Agent and Coach memory pipelines."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.learning_event import EventCategory, LearningEvent


EVENT_TYPE_ALIASES = {
    "goal_set": "goal.created",
    "goal_updated": "goal.updated",
    "note_created": "note.created",
    "note_updated": "note.updated",
    "material_uploaded": "material.uploaded",
    "pomodoro_start": "pomodoro.started",
    "pomodoro_complete": "pomodoro.completed",
    "pomodoro_interrupt": "pomodoro.interrupted",
    "review_complete": "review.completed",
}

EVENT_CATEGORY_BY_PREFIX = {
    "goal": EventCategory.GOAL,
    "task": EventCategory.GOAL,
    "daily_plan": EventCategory.GOAL,
    "note": EventCategory.STUDY,
    "material": EventCategory.STUDY,
    "wrong_question": EventCategory.PRACTICE,
    "review": EventCategory.REVIEW,
    "pomodoro": EventCategory.PRACTICE,
    "chat": EventCategory.INTERACTION,
    "agent": EventCategory.INTERACTION,
    "coach": EventCategory.INTERACTION,
}


def normalize_learning_event_type(event_type: str) -> str:
    """Return the canonical dot-style event name while accepting legacy names."""

    raw = str(event_type or "").strip()
    if not raw:
        raise ValueError("event_type 不能为空")
    if raw in EVENT_TYPE_ALIASES:
        return EVENT_TYPE_ALIASES[raw]
    return raw if "." in raw else raw.replace("_", ".")


def _event_category_for(event_type: str) -> str:
    prefix = event_type.split(".", 1)[0]
    return EVENT_CATEGORY_BY_PREFIX.get(prefix, EventCategory.INTERACTION)


def _to_iso(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def learning_event_to_dict(event: LearningEvent) -> dict[str, Any]:
    return {
        "id": event.id,
        "user_id": event.user_id,
        "event_type": event.event_type,
        "event_category": event.event_category,
        "source": event.source,
        "payload": event.event_data or {},
        "event_data": event.event_data or {},
        "timestamp": _to_iso(event.timestamp),
        "duration": event.duration,
        "material_id": event.material_id,
        "chapter_id": event.chapter_id,
        "goal_id": event.goal_id,
        "task_id": event.task_id,
        "note_id": event.note_id,
        "wrong_question_id": event.wrong_question_id,
        "session_id": event.session_id,
        "dedupe_key": event.dedupe_key,
        "metadata": event.extra_metadata or {},
    }


async def record_learning_event(
    db: AsyncSession,
    user_id: int,
    event_type: str,
    *,
    source: str,
    payload: dict[str, Any] | None = None,
    material_id: int | None = None,
    chapter_id: int | None = None,
    goal_id: int | None = None,
    task_id: int | None = None,
    note_id: int | None = None,
    wrong_question_id: int | None = None,
    duration: int | None = None,
    session_id: str | None = None,
    dedupe_key: str | None = None,
    occurred_at: datetime | None = None,
) -> dict[str, Any]:
    """Record one user-scoped learning event, returning an existing recent row on dedupe."""

    normalized_type = normalize_learning_event_type(event_type)[:50]
    clean_source = str(source or "unknown").strip()[:50] or "unknown"
    clean_dedupe = str(dedupe_key or "").strip()[:160] or None
    timestamp = occurred_at or datetime.now()

    if clean_dedupe:
        cutoff = timestamp - timedelta(hours=24)
        result = await db.execute(
            select(LearningEvent)
            .where(
                LearningEvent.user_id == user_id,
                LearningEvent.event_type == normalized_type,
                LearningEvent.dedupe_key == clean_dedupe,
                LearningEvent.timestamp >= cutoff,
            )
            .order_by(LearningEvent.timestamp.desc(), LearningEvent.id.desc())
            .limit(1)
        )
        existing = result.scalar_one_or_none()
        if existing:
            return learning_event_to_dict(existing)

    data = dict(payload or {})
    event = LearningEvent(
        user_id=user_id,
        event_type=normalized_type,
        event_category=_event_category_for(normalized_type),
        source=clean_source,
        dedupe_key=clean_dedupe,
        event_data=data,
        timestamp=timestamp,
        duration=duration,
        material_id=material_id,
        chapter_id=chapter_id,
        goal_id=goal_id,
        task_id=task_id,
        note_id=note_id,
        wrong_question_id=wrong_question_id,
        session_id=str(session_id)[:50] if session_id is not None else None,
    )
    db.add(event)
    await db.flush()
    await db.refresh(event)
    return learning_event_to_dict(event)


async def list_recent_learning_events(
    db: AsyncSession,
    user_id: int,
    *,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """List recent user-scoped learning events newest first."""

    result = await db.execute(
        select(LearningEvent)
        .where(LearningEvent.user_id == user_id)
        .order_by(LearningEvent.timestamp.desc(), LearningEvent.id.desc())
        .limit(max(1, min(int(limit or 100), 200)))
    )
    return [learning_event_to_dict(row) for row in result.scalars().all()]
