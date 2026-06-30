"""Coach action/nudge persistence."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.coach import CoachNudge
from app.services.coach_learning_service import record_skill_shown
from app.services.coach_skills.base import CoachSkillResult


def coach_nudge_to_dict(row: CoachNudge) -> dict[str, Any]:
    return {
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
        "expires_at": row.expires_at.isoformat() if row.expires_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


async def create_coach_nudge(
    db: AsyncSession,
    user_id: int,
    *,
    event_id: str | None,
    skill_id: str,
    policy: dict[str, Any],
    result: CoachSkillResult,
) -> dict[str, Any]:
    nudge = CoachNudge(
        id=f"cn_{uuid4().hex[:24]}",
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
        },
        status="pending",
        expires_at=datetime.now() + timedelta(hours=24),
    )
    db.add(nudge)
    await db.flush()
    await db.refresh(nudge)
    return coach_nudge_to_dict(nudge)


async def list_coach_nudges(
    db: AsyncSession,
    user_id: int,
    *,
    status: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    query = select(CoachNudge).where(CoachNudge.user_id == user_id)
    if status:
        query = query.where(CoachNudge.status == status)
    query = query.order_by(CoachNudge.created_at.desc()).limit(max(1, min(int(limit or 20), 100)))
    result = await db.execute(query)
    return [coach_nudge_to_dict(row) for row in result.scalars().all()]


async def mark_coach_nudge_shown(db: AsyncSession, user_id: int, nudge_id: str) -> dict[str, Any] | None:
    result = await db.execute(select(CoachNudge).where(CoachNudge.id == nudge_id, CoachNudge.user_id == user_id))
    row = result.scalar_one_or_none()
    if not row:
        return None
    should_count_shown = row.status == "pending"
    if should_count_shown:
        row.status = "shown"
        row.updated_at = datetime.now()
        await record_skill_shown(db, user_id, row)
    await db.flush()
    return coach_nudge_to_dict(row)
