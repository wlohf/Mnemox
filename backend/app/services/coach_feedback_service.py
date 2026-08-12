"""Coach nudge feedback and learned preference memory."""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.coach import CoachNudge
from app.models.memory import UserMemory
from app.services.coach_learning_service import record_skill_feedback
from app.services.learning_event_service import CanonicalEventType, record_coach_nudge_event

CONFIRMED_REVIEW_STATUS = "confirmed"


COACH_FEEDBACK_OUTCOMES = {
    "helpful",
    "accepted",
    "completed",
    "later",
    "snoozed",
    "dismissed",
    "too_disruptive",
    "too_hard",
    "too_easy",
    "irrelevant",
    "not_my_style",
}
SNOOZE_DURATIONS = {
    "later": timedelta(hours=2),
    "snoozed": timedelta(hours=4),
}


def _feedback_status(outcome: str) -> str:
    if outcome == "completed":
        return "completed"
    if outcome in {"accepted", "helpful"}:
        return "accepted"
    if outcome in {"later", "snoozed"}:
        return "snoozed"
    return "dismissed"


def _feedback_event_type(outcome: str) -> str:
    """Map user feedback to the lifecycle event used by attribution metrics."""

    if outcome in {"accepted", "helpful"}:
        return CanonicalEventType.COACH_NUDGE_ACCEPTED
    if outcome == "completed":
        return CanonicalEventType.COACH_NUDGE_COMPLETED
    if outcome in {"later", "snoozed"}:
        return CanonicalEventType.COACH_NUDGE_SNOOZED
    if outcome in {"dismissed", "too_disruptive"}:
        return CanonicalEventType.COACH_NUDGE_DISMISSED
    return CanonicalEventType.COACH_NUDGE_FEEDBACK


async def record_coach_feedback(
    db: AsyncSession,
    user_id: int,
    nudge_id: str,
    outcome: str,
    notes: str | None = None,
) -> dict[str, Any]:
    outcome = str(outcome or "").strip()
    if outcome not in COACH_FEEDBACK_OUTCOMES:
        raise ValueError("不支持的反馈类型")

    result = await db.execute(select(CoachNudge).where(CoachNudge.id == nudge_id, CoachNudge.user_id == user_id))
    nudge = result.scalar_one_or_none()
    if not nudge:
        raise ValueError("Coach nudge 不存在或无权访问")

    now = datetime.now()
    nudge.status = _feedback_status(outcome)
    nudge.updated_at = now

    payload = {
        "nudge_id": nudge.id,
        "event_id": nudge.event_id,
        "skill_id": nudge.skill_id,
        "channel": nudge.channel,
        "priority": nudge.priority,
        "title": nudge.title,
        "outcome": outcome,
        "notes": (notes or "")[:500],
        "recorded_at": now.isoformat(),
    }
    if outcome in SNOOZE_DURATIONS:
        payload["snooze_until"] = (now + SNOOZE_DURATIONS[outcome]).isoformat()
    memory = UserMemory(
        user_id=user_id,
        memory_key=f"coach_feedback_{now.strftime('%Y%m%d_%H%M%S%f')}_{nudge.skill_id}"[:100],
        memory_value=json.dumps(payload, ensure_ascii=False),
        category="coach_feedback",
        confidence=0.8,
        status="active",
        review_status=CONFIRMED_REVIEW_STATUS,
        is_locked=0,
        memory_type="episodic",
        last_seen_at=now,
    )
    db.add(memory)
    learning_stats = await record_skill_feedback(db, user_id, nudge, outcome)
    await record_coach_nudge_event(
        db,
        user_id,
        nudge,
        _feedback_event_type(outcome),
        outcome=outcome,
        occurred_at=now,
    )
    await db.flush()
    return {
        "ok": True,
        "nudge_id": nudge.id,
        "status": nudge.status,
        "memory_key": memory.memory_key,
        "learning_stats": learning_stats,
    }


async def list_recent_coach_feedback(db: AsyncSession, user_id: int, limit: int = 30) -> list[dict[str, Any]]:
    result = await db.execute(
        select(UserMemory)
        .where(
            UserMemory.user_id == user_id,
            UserMemory.category == "coach_feedback",
            UserMemory.status == "active",
            UserMemory.review_status == CONFIRMED_REVIEW_STATUS,
        )
        .order_by(UserMemory.last_seen_at.desc(), UserMemory.updated_at.desc())
        .limit(max(1, min(int(limit or 30), 100)))
    )
    items: list[dict[str, Any]] = []
    for row in result.scalars().all():
        try:
            payload = json.loads(row.memory_value or "{}")
        except Exception:
            payload = {}
        if isinstance(payload, dict):
            payload.setdefault("memory_key", row.memory_key)
            payload.setdefault("recorded_at", row.last_seen_at.isoformat() if row.last_seen_at else None)
            items.append(payload)
    return items
