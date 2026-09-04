"""Coach nudge feedback and learned preference memory."""
from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.coach import CoachNudge
from app.models.memory import UserMemory
from app.services.coach_learning_service import record_skill_feedback
from app.services.learning_event_service import CanonicalEventType, record_coach_nudge_event
from app.utils.utc import to_utc_iso, utc_now_db

CONFIRMED_REVIEW_STATUS = "confirmed"


COACH_FEEDBACK_OUTCOMES = {
    "helpful",
    "accepted",
    "started",
    "completed",
    "abandoned",
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
IDEMPOTENT_FEEDBACK_OUTCOMES = {"accepted", "helpful", "started", "completed", "abandoned"}


def _feedback_status(outcome: str) -> str:
    if outcome == "completed":
        return "completed"
    if outcome == "abandoned":
        return "abandoned"
    if outcome == "started":
        return "started"
    if outcome in {"accepted", "helpful"}:
        return "accepted"
    if outcome in {"later", "snoozed"}:
        return "snoozed"
    return "dismissed"


def _feedback_event_type(outcome: str) -> str:
    """Map user feedback to the lifecycle event used by attribution metrics."""

    if outcome in {"accepted", "helpful"}:
        return CanonicalEventType.COACH_NUDGE_ACCEPTED
    if outcome == "started":
        return CanonicalEventType.COACH_NUDGE_STARTED
    if outcome == "completed":
        return CanonicalEventType.COACH_NUDGE_COMPLETED
    if outcome == "abandoned":
        return CanonicalEventType.COACH_NUDGE_ABANDONED
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
    attribution: dict[str, Any] | None = None,
) -> dict[str, Any]:
    outcome = str(outcome or "").strip()
    if outcome not in COACH_FEEDBACK_OUTCOMES:
        raise ValueError("不支持的反馈类型")

    now = utc_now_db()
    target_status = _feedback_status(outcome)
    if outcome in IDEMPOTENT_FEEDBACK_OUTCOMES:
        allowed_statuses_by_outcome = {
            "accepted": ("pending", "shown", "snoozed"),
            "helpful": ("pending", "shown", "snoozed"),
            "started": ("pending", "shown", "accepted", "snoozed"),
            "completed": ("pending", "shown", "accepted", "started", "snoozed"),
            "abandoned": ("pending", "shown", "accepted", "started", "snoozed"),
        }
        allowed_statuses = allowed_statuses_by_outcome[outcome]
        transition = await db.execute(
            update(CoachNudge)
            .where(
                CoachNudge.id == nudge_id,
                CoachNudge.user_id == user_id,
                CoachNudge.status.in_(allowed_statuses),
            )
            .values(status=target_status, updated_at=now)
        )
        result = await db.execute(
            select(CoachNudge).where(CoachNudge.id == nudge_id, CoachNudge.user_id == user_id)
        )
        nudge = result.scalar_one_or_none()
        if not nudge:
            raise ValueError("Coach nudge 不存在或无权访问")
        if int(transition.rowcount or 0) == 0:
            return {
                "ok": True,
                "nudge_id": nudge.id,
                "status": nudge.status,
                "idempotent": True,
                "learning_stats": None,
            }
    else:
        result = await db.execute(
            select(CoachNudge).where(CoachNudge.id == nudge_id, CoachNudge.user_id == user_id)
        )
        nudge = result.scalar_one_or_none()
        if not nudge:
            raise ValueError("Coach nudge 不存在或无权访问")
        nudge.status = target_status
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
        "recorded_at": to_utc_iso(now),
    }
    if attribution:
        payload["attribution"] = {
            key: value
            for key, value in attribution.items()
            if key in {"method", "attempt_id", "action_type", "linked_event_id", "linked_event_type", "reason"}
            and value is not None
        }
    if outcome in SNOOZE_DURATIONS:
        payload["snooze_until"] = to_utc_iso(now + SNOOZE_DURATIONS[outcome])
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
        attribution=attribution,
        occurred_at=now,
    )
    # Automatic outcomes (for example a completed Pomodoro) must feed the
    # same self-quote loop as a button-clicked response.  The router keeps a
    # defensive retry for legacy callers; this update is idempotent.
    try:
        from app.services.note_quote_service import attach_note_quote_feedback

        await attach_note_quote_feedback(db, user_id, nudge.id, outcome)
    except Exception:
        # Quote analytics must never make the Coach action itself fail.
        pass
    attempt = None
    if outcome in {"completed", "abandoned"}:
        # A manual confirmation and a verified domain event both use the same
        # terminal path.  The action-attempt row adds the provenance needed to
        # tell them apart during replay and metrics aggregation.
        from app.services.coach_action_attempt_service import sync_attempt_from_feedback

        attempt = await sync_attempt_from_feedback(
            db,
            user_id,
            nudge,
            outcome,
            attribution=attribution,
        )
    await db.flush()
    return {
        "ok": True,
        "nudge_id": nudge.id,
        "status": nudge.status,
        "memory_key": memory.memory_key,
        "learning_stats": learning_stats,
        "attempt": attempt,
    }


async def list_recent_coach_feedback(db: AsyncSession, user_id: int, limit: int = 30) -> list[dict[str, Any]]:
    result = await db.execute(
        select(UserMemory)
        .where(
            UserMemory.user_id == user_id,
            UserMemory.category == "coach_feedback",
            UserMemory.status == "active",
            UserMemory.review_status == CONFIRMED_REVIEW_STATUS,
            or_(UserMemory.expires_at.is_(None), UserMemory.expires_at > utc_now_db()),
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
            payload.setdefault("recorded_at", to_utc_iso(row.last_seen_at) if row.last_seen_at else None)
            items.append(payload)
    return items
