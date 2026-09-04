"""Coach action/nudge persistence."""
from __future__ import annotations

from datetime import timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.coach import CoachNudge
from app.services.coach_experiment_service import build_coach_experiment_assignment
from app.services.coach_learning_service import record_skill_shown
from app.services.coach_skills.base import CoachSkillResult
from app.services.learning_event_service import CanonicalEventType, record_coach_nudge_event
from app.utils.utc import to_utc_iso, utc_now_db


def coach_nudge_to_dict(row: CoachNudge, *, action_attempt: dict[str, Any] | None = None) -> dict[str, Any]:
    result = {
        "id": row.id,
        "user_id": row.user_id,
        "event_id": row.event_id,
        "skill_id": row.skill_id,
        "channel": row.channel,
        "priority": row.priority,
        "title": row.title,
        "body": row.body,
        "suggested_action": row.suggested_action or {},
        "route": row.route,
        "requires_confirmation": bool(row.requires_confirmation),
        "draft": row.draft,
        "explainability": row.explainability,
        "status": row.status,
        "expires_at": to_utc_iso(row.expires_at) if row.expires_at else None,
        "created_at": to_utc_iso(row.created_at) if row.created_at else None,
        "updated_at": to_utc_iso(row.updated_at) if row.updated_at else None,
    }
    if action_attempt is not None:
        result["action_attempt"] = action_attempt
    return result


async def create_coach_nudge(
    db: AsyncSession,
    user_id: int,
    *,
    event_id: str | None,
    skill_id: str,
    policy: dict[str, Any],
    result: CoachSkillResult,
    nudge_id: str | None = None,
) -> dict[str, Any]:
    experiment = build_coach_experiment_assignment(user_id)
    nudge = CoachNudge(
        id=str(nudge_id or f"cn_{uuid4().hex[:24]}")[:40],
        user_id=user_id,
        event_id=event_id,
        skill_id=skill_id,
        channel=str(policy.get("channel") or "in_app_nudge"),
        priority=str(policy.get("priority") or "medium"),
        title=result.title[:80],
        body=result.body[:500],
        suggested_action=result.suggested_action or {},
        route=result.route or (result.suggested_action or {}).get("route"),
        requires_confirmation=bool(result.requires_confirmation),
        draft=result.draft,
        explainability={
            **(result.explainability or {}),
            "policy": {
                "reason": policy.get("reason"),
                "evidence": policy.get("evidence") or [],
            },
            **({"experiment": experiment} if experiment is not None else {}),
        },
        status="pending",
        expires_at=utc_now_db() + timedelta(hours=24),
    )
    db.add(nudge)
    await db.flush()
    await db.refresh(nudge)
    await record_coach_nudge_event(
        db,
        user_id,
        nudge,
        CanonicalEventType.COACH_NUDGE_CREATED,
    )
    return coach_nudge_to_dict(nudge)


async def list_coach_nudges(
    db: AsyncSession,
    user_id: int,
    *,
    status: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    from app.services.coach_action_attempt_service import (
        expire_due_coach_nudges,
        latest_action_attempts_by_nudge,
    )

    await expire_due_coach_nudges(db, user_id)
    query = select(CoachNudge).where(CoachNudge.user_id == user_id)
    if status:
        query = query.where(CoachNudge.status == status)
    query = query.order_by(CoachNudge.created_at.desc()).limit(max(1, min(int(limit or 20), 100)))
    result = await db.execute(query)
    rows = list(result.scalars().all())
    latest_attempts = await latest_action_attempts_by_nudge(db, user_id, [row.id for row in rows])
    return [coach_nudge_to_dict(row, action_attempt=latest_attempts.get(row.id)) for row in rows]


async def mark_coach_nudge_shown(db: AsyncSession, user_id: int, nudge_id: str) -> dict[str, Any] | None:
    from app.services.coach_action_attempt_service import expire_due_coach_nudges

    await expire_due_coach_nudges(db, user_id)
    now = utc_now_db()
    transition = await db.execute(
        update(CoachNudge)
        .where(
            CoachNudge.id == nudge_id,
            CoachNudge.user_id == user_id,
            CoachNudge.status == "pending",
        )
        .values(status="shown", updated_at=now)
    )
    result = await db.execute(
        select(CoachNudge).where(CoachNudge.id == nudge_id, CoachNudge.user_id == user_id)
    )
    row = result.scalar_one_or_none()
    if not row:
        return None
    if int(transition.rowcount or 0) > 0:
        await record_skill_shown(db, user_id, row)
        await record_coach_nudge_event(
            db,
            user_id,
            row,
            CanonicalEventType.COACH_NUDGE_SHOWN,
            occurred_at=now,
        )
    await db.flush()
    return coach_nudge_to_dict(row)
