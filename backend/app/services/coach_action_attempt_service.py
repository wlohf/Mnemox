"""Durable attribution from a Coach suggestion to a real learning action.

The Coach nudge itself is intentionally only a recommendation.  This service
adds an immutable-friendly bridge that starts when the learner chooses the
suggested action and closes only through either an explicit learner decision or
a linked domain event (Pomodoro, review completion, or a confirmed plan draft).
"""
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.coach import CoachActionAttempt, CoachNudge
from app.models.learning_event import LearningEvent
from app.services.learning_event_service import CanonicalEventType, learning_event_to_dict, record_coach_nudge_event


ACTIVE_ATTEMPT_STATUSES = {"started"}
TERMINAL_ATTEMPT_STATUSES = {"completed", "abandoned", "expired"}
TERMINAL_NUDGE_STATUSES = {"completed", "abandoned", "dismissed", "expired"}


def coach_action_attempt_to_dict(row: CoachActionAttempt) -> dict[str, Any]:
    return {
        "id": row.id,
        "nudge_id": row.nudge_id,
        "action_type": row.action_type,
        "route": row.route,
        "action_payload": row.action_payload or {},
        "status": row.status,
        "started_at": row.started_at.isoformat() if row.started_at else None,
        "observed_at": row.observed_at.isoformat() if row.observed_at else None,
        "completed_at": row.completed_at.isoformat() if row.completed_at else None,
        "abandoned_at": row.abandoned_at.isoformat() if row.abandoned_at else None,
        "expires_at": row.expires_at.isoformat() if row.expires_at else None,
        "linked_event_id": row.linked_event_id,
        "linked_event_type": row.linked_event_type,
        "outcome_source": row.outcome_source,
        "outcome_reason": row.outcome_reason,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _attempt_accepts_domain_event(attempt: CoachActionAttempt, event_type: str) -> bool:
    """Keep an attribution token scoped to the action the learner selected."""

    route = str(attempt.route or "")
    action_type = str(attempt.action_type or "")
    if event_type.startswith("pomodoro."):
        return route == "/pomodoro" or action_type == "start_focus"
    if event_type.startswith("review."):
        return route == "/review"
    if event_type.startswith("daily_plan."):
        return route == "/plans" and action_type == "create_daily_plan_draft"
    return False


async def _latest_active_attempt(
    db: AsyncSession,
    user_id: int,
    nudge_id: str,
) -> CoachActionAttempt | None:
    result = await db.execute(
        select(CoachActionAttempt)
        .where(
            CoachActionAttempt.user_id == int(user_id),
            CoachActionAttempt.nudge_id == nudge_id,
            CoachActionAttempt.status.in_(ACTIVE_ATTEMPT_STATUSES),
        )
        .order_by(CoachActionAttempt.started_at.desc(), CoachActionAttempt.id.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def get_coach_action_attempt(
    db: AsyncSession,
    user_id: int,
    attempt_id: str,
) -> CoachActionAttempt | None:
    return await db.scalar(
        select(CoachActionAttempt).where(
            CoachActionAttempt.id == str(attempt_id),
            CoachActionAttempt.user_id == int(user_id),
        )
    )


async def list_coach_action_attempts(
    db: AsyncSession,
    user_id: int,
    *,
    nudge_id: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    query = select(CoachActionAttempt).where(CoachActionAttempt.user_id == int(user_id))
    if nudge_id:
        query = query.where(CoachActionAttempt.nudge_id == str(nudge_id))
    result = await db.execute(
        query.order_by(CoachActionAttempt.started_at.desc(), CoachActionAttempt.id.desc())
        .limit(max(1, min(int(limit or 50), 200)))
    )
    return [coach_action_attempt_to_dict(row) for row in result.scalars().all()]


async def get_coach_nudge_replay(
    db: AsyncSession,
    user_id: int,
    nudge_id: str,
) -> dict[str, Any] | None:
    """Return the bounded, user-scoped evidence needed to replay one nudge."""

    nudge = await db.scalar(
        select(CoachNudge).where(
            CoachNudge.id == str(nudge_id),
            CoachNudge.user_id == int(user_id),
        )
    )
    if not nudge:
        return None
    attempts = await list_coach_action_attempts(db, user_id, nudge_id=nudge.id, limit=50)
    attempt_ids = {str(item["id"]) for item in attempts}
    linked_event_ids = {
        int(item["linked_event_id"])
        for item in attempts
        if item.get("linked_event_id") is not None
    }

    # Coach lifecycle rows carry the nudge/attempt ID in a compact payload.
    # JSON filtering differs between SQLite and PostgreSQL, so keep the query
    # portable and bound the scan to the post-nudge window for this beta API.
    result = await db.execute(
        select(LearningEvent)
        .where(
            LearningEvent.user_id == int(user_id),
            LearningEvent.timestamp >= (nudge.created_at or datetime.min),
        )
        .order_by(LearningEvent.timestamp.asc(), LearningEvent.id.asc())
        .limit(500)
    )
    timeline: list[dict[str, Any]] = []
    for event in result.scalars().all():
        payload = event.event_data if isinstance(event.event_data, dict) else {}
        attribution = payload.get("attribution") if isinstance(payload.get("attribution"), dict) else {}
        related = (
            str(payload.get("nudge_id") or "") == nudge.id
            or str(payload.get("coach_action_attempt_id") or "") in attempt_ids
            or str(attribution.get("attempt_id") or "") in attempt_ids
            or int(event.id) in linked_event_ids
        )
        if related:
            timeline.append(learning_event_to_dict(event))
    return {
        "nudge": _nudge_summary(nudge),
        "trigger_event_id": nudge.event_id,
        "attempts": attempts,
        "timeline": timeline,
    }


async def latest_action_attempts_by_nudge(
    db: AsyncSession,
    user_id: int,
    nudge_ids: list[str],
) -> dict[str, dict[str, Any]]:
    clean_ids = list(dict.fromkeys(str(item) for item in nudge_ids if item))
    if not clean_ids:
        return {}
    result = await db.execute(
        select(CoachActionAttempt)
        .where(
            CoachActionAttempt.user_id == int(user_id),
            CoachActionAttempt.nudge_id.in_(clean_ids),
        )
        .order_by(CoachActionAttempt.started_at.desc(), CoachActionAttempt.id.desc())
    )
    latest: dict[str, dict[str, Any]] = {}
    for row in result.scalars().all():
        latest.setdefault(str(row.nudge_id), coach_action_attempt_to_dict(row))
    return latest


async def start_coach_action_attempt(
    db: AsyncSession,
    user_id: int,
    nudge_id: str,
) -> dict[str, Any]:
    """Start a suggested action without auto-executing any write.

    The learner click is enough to record acceptance and intent.  The actual
    learning result is attached later by the target domain endpoint, so this
    never treats navigation alone as a completed learning action.
    """

    nudge = await db.scalar(
        select(CoachNudge).where(
            CoachNudge.id == str(nudge_id),
            CoachNudge.user_id == int(user_id),
        )
    )
    if not nudge:
        raise ValueError("Coach nudge 不存在或无权访问")
    if nudge.status in TERMINAL_NUDGE_STATUSES:
        raise ValueError("这条 Coach 建议已结束，不能再开始行动")

    existing = await _latest_active_attempt(db, user_id, nudge.id)
    if existing:
        return {
            "ok": True,
            "idempotent": True,
            "nudge": _nudge_summary(nudge),
            "attempt": coach_action_attempt_to_dict(existing),
        }

    now = datetime.now()
    action = nudge.suggested_action or {}
    attempt = CoachActionAttempt(
        id=f"ca_{uuid4().hex[:24]}",
        user_id=int(user_id),
        nudge_id=nudge.id,
        action_type=str(action.get("type") or "open_route")[:80],
        route=str(nudge.route or action.get("route") or "")[:200] or None,
        action_payload=dict(action),
        status="started",
        started_at=now,
        expires_at=nudge.expires_at,
    )
    db.add(attempt)
    await db.flush()

    # Import locally to keep the feedback service usable on its own and avoid
    # an import cycle.  These two transitions also update learned skill stats
    # and append the canonical lifecycle ledger rows.
    from app.services.coach_feedback_service import record_coach_feedback

    attribution = {
        "method": "learner_action_intent",
        "attempt_id": attempt.id,
        "action_type": attempt.action_type,
    }
    if nudge.status in {"pending", "shown", "snoozed"}:
        await record_coach_feedback(
            db,
            int(user_id),
            nudge.id,
            "accepted",
            attribution=attribution,
        )
    await record_coach_feedback(
        db,
        int(user_id),
        nudge.id,
        "started",
        attribution=attribution,
    )
    await db.flush()
    await db.refresh(nudge)
    return {
        "ok": True,
        "idempotent": False,
        "nudge": _nudge_summary(nudge),
        "attempt": coach_action_attempt_to_dict(attempt),
    }


async def bind_coach_attempt_to_domain_event(
    db: AsyncSession,
    user_id: int,
    attempt_id: str | None,
    *,
    event_id: int,
    event_type: str,
    outcome: str | None = None,
    reason: str | None = None,
) -> dict[str, Any] | None:
    """Attach a verified domain event and, when terminal, close the attempt.

    The caller supplies the event ID only after the domain record and common
    learning ledger entry exist in the same transaction.  This prevents a
    frontend-only click from claiming a Pomodoro or review was completed.
    """

    clean_id = str(attempt_id or "").strip()
    if not clean_id:
        return None
    attempt = await get_coach_action_attempt(db, int(user_id), clean_id)
    if not attempt:
        raise ValueError("Coach 行动尝试不存在或无权访问")
    nudge = await db.scalar(
        select(CoachNudge).where(
            CoachNudge.id == attempt.nudge_id,
            CoachNudge.user_id == int(user_id),
        )
    )
    if not nudge:
        raise ValueError("关联的 Coach nudge 不存在")
    if not _attempt_accepts_domain_event(attempt, str(event_type)):
        raise ValueError("该 Coach 建议不能归因到此学习行为")

    if attempt.status in TERMINAL_ATTEMPT_STATUSES:
        return {
            "ok": True,
            "idempotent": True,
            "attempt": coach_action_attempt_to_dict(attempt),
            "nudge": _nudge_summary(nudge),
        }

    now = datetime.now()
    attempt.observed_at = now
    attempt.linked_event_id = int(event_id)
    attempt.linked_event_type = str(event_type)[:80]
    if outcome not in {"completed", "abandoned"}:
        await db.flush()
        await db.refresh(attempt)
        return {
            "ok": True,
            "idempotent": False,
            "attempt": coach_action_attempt_to_dict(attempt),
            "nudge": _nudge_summary(nudge),
        }

    from app.services.coach_feedback_service import record_coach_feedback

    feedback = await record_coach_feedback(
        db,
        int(user_id),
        nudge.id,
        outcome,
        notes=reason,
        attribution={
            "method": "domain_event",
            "attempt_id": attempt.id,
            "action_type": attempt.action_type,
            "linked_event_id": int(event_id),
            "linked_event_type": str(event_type)[:80],
        },
    )
    # ``record_coach_feedback`` updates the attempt as well.  Keep this
    # assignment defensive for callers that use the service directly in an
    # older transaction shape.
    attempt.status = outcome
    attempt.outcome_source = "domain_event"
    attempt.outcome_reason = (reason or "")[:120] or None
    if outcome == "completed":
        attempt.completed_at = now
    else:
        attempt.abandoned_at = now
    await db.flush()
    await db.refresh(attempt)
    await db.refresh(nudge)
    return {
        "ok": True,
        "idempotent": bool(feedback.get("idempotent")),
        "attempt": coach_action_attempt_to_dict(attempt),
        "nudge": _nudge_summary(nudge),
    }


async def sync_attempt_from_feedback(
    db: AsyncSession,
    user_id: int,
    nudge: CoachNudge,
    outcome: str,
    *,
    attribution: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Close the active attempt after an explicit learner terminal response."""

    if outcome not in {"completed", "abandoned"}:
        return None
    attempt_id = str((attribution or {}).get("attempt_id") or "").strip()
    if attempt_id:
        attempt = await get_coach_action_attempt(db, int(user_id), attempt_id)
        if not attempt or attempt.nudge_id != nudge.id:
            return None
    else:
        attempt = await _latest_active_attempt(db, int(user_id), nudge.id)
    if not attempt or attempt.status in TERMINAL_ATTEMPT_STATUSES:
        return coach_action_attempt_to_dict(attempt) if attempt else None

    now = datetime.now()
    attempt.status = outcome
    method = str((attribution or {}).get("method") or "learner_confirmation")[:40]
    attempt.outcome_source = method
    attempt.outcome_reason = str((attribution or {}).get("reason") or "")[:120] or None
    linked_event_id = (attribution or {}).get("linked_event_id")
    if linked_event_id is not None:
        try:
            attempt.linked_event_id = int(linked_event_id)
        except (TypeError, ValueError):
            pass
    linked_event_type = str((attribution or {}).get("linked_event_type") or "")[:80]
    if linked_event_type:
        attempt.linked_event_type = linked_event_type
    attempt.observed_at = now
    if outcome == "completed":
        attempt.completed_at = now
    else:
        attempt.abandoned_at = now
    await db.flush()
    # ``updated_at`` is database-generated.  Refresh before serializing so an
    # async session never attempts an implicit lazy load outside greenlet.
    await db.refresh(attempt)
    return coach_action_attempt_to_dict(attempt)


async def expire_due_coach_nudges(db: AsyncSession, user_id: int, *, now: datetime | None = None) -> int:
    """Close stale nudges without pretending that silence is negative feedback."""

    current = now or datetime.now()
    result = await db.execute(
        select(CoachNudge).where(
            CoachNudge.user_id == int(user_id),
            CoachNudge.expires_at.is_not(None),
            CoachNudge.expires_at <= current,
            CoachNudge.status.in_(["pending", "shown", "accepted", "started", "snoozed"]),
        )
    )
    expired = list(result.scalars().all())
    for nudge in expired:
        nudge.status = "expired"
        nudge.updated_at = current
        attempts = await db.execute(
            select(CoachActionAttempt).where(
                CoachActionAttempt.user_id == int(user_id),
                CoachActionAttempt.nudge_id == nudge.id,
                CoachActionAttempt.status.in_(ACTIVE_ATTEMPT_STATUSES),
            )
        )
        for attempt in attempts.scalars().all():
            attempt.status = "expired"
            attempt.outcome_source = "time_window_expired"
            attempt.expires_at = current
            attempt.updated_at = current
        await record_coach_nudge_event(
            db,
            int(user_id),
            nudge,
            CanonicalEventType.COACH_NUDGE_EXPIRED,
            outcome="expired",
            attribution={"method": "time_window_expired"},
            occurred_at=current,
        )
    await db.flush()
    return len(expired)


def _nudge_summary(nudge: CoachNudge) -> dict[str, Any]:
    return {
        "id": nudge.id,
        "skill_id": nudge.skill_id,
        "status": nudge.status,
        "title": nudge.title,
        "route": nudge.route,
        "suggested_action": nudge.suggested_action or {},
        "requires_confirmation": bool(nudge.requires_confirmation),
        "explainability": nudge.explainability or {},
    }
