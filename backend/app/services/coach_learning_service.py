"""Coach feedback aggregation used by the intervention policy."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.coach import CoachEvent, CoachNudge, CoachSkillStats


POSITIVE_OUTCOMES = {"helpful", "accepted", "completed"}
NEGATIVE_OUTCOMES = {"dismissed", "too_disruptive", "too_hard", "too_easy", "irrelevant", "not_my_style"}
SNOOZE_OUTCOMES = {"later", "snoozed"}
OUTCOME_COLUMNS = {
    "helpful": "helpful_count",
    "accepted": "accepted_count",
    "completed": "completed_count",
    "later": "snoozed_count",
    "snoozed": "snoozed_count",
    "dismissed": "dismissed_count",
    "too_disruptive": "too_disruptive_count",
    "too_hard": "too_hard_count",
    "too_easy": "too_easy_count",
    "irrelevant": "irrelevant_count",
    "not_my_style": "not_my_style_count",
}


def coach_skill_stats_to_dict(row: CoachSkillStats) -> dict[str, Any]:
    return {
        "id": row.id,
        "user_id": row.user_id,
        "skill_id": row.skill_id,
        "channel": row.channel,
        "event_type": row.event_type,
        "shown_count": row.shown_count,
        "accepted_count": row.accepted_count,
        "completed_count": row.completed_count,
        "helpful_count": row.helpful_count,
        "snoozed_count": row.snoozed_count,
        "dismissed_count": row.dismissed_count,
        "too_disruptive_count": row.too_disruptive_count,
        "too_hard_count": row.too_hard_count,
        "too_easy_count": row.too_easy_count,
        "irrelevant_count": row.irrelevant_count,
        "not_my_style_count": row.not_my_style_count,
        "recent_score": row.recent_score,
        "lifetime_score": row.lifetime_score,
        "last_shown_at": row.last_shown_at.isoformat() if row.last_shown_at else None,
        "last_positive_at": row.last_positive_at.isoformat() if row.last_positive_at else None,
        "last_negative_at": row.last_negative_at.isoformat() if row.last_negative_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


async def _event_type_for_nudge(db: AsyncSession, user_id: int, nudge: CoachNudge) -> str:
    if not nudge.event_id:
        return ""
    result = await db.execute(
        select(CoachEvent.event_type).where(CoachEvent.id == nudge.event_id, CoachEvent.user_id == user_id)
    )
    return str(result.scalar_one_or_none() or "")


async def _get_or_create_stats(
    db: AsyncSession,
    user_id: int,
    *,
    skill_id: str,
    channel: str,
    event_type: str,
) -> CoachSkillStats:
    result = await db.execute(
        select(CoachSkillStats).where(
            CoachSkillStats.user_id == user_id,
            CoachSkillStats.skill_id == skill_id,
            CoachSkillStats.channel == channel,
            CoachSkillStats.event_type == event_type,
        )
    )
    row = result.scalar_one_or_none()
    if row:
        return row

    row = CoachSkillStats(
        user_id=user_id,
        skill_id=skill_id,
        channel=channel,
        event_type=event_type,
    )
    db.add(row)
    await db.flush()
    return row


def _apply_score(row: CoachSkillStats, delta: float, now: datetime) -> None:
    row.lifetime_score = float(row.lifetime_score or 0.0) + delta
    row.recent_score = (float(row.recent_score or 0.0) * 0.7) + delta
    row.updated_at = now


async def record_skill_shown(db: AsyncSession, user_id: int, nudge: CoachNudge) -> dict[str, Any]:
    """Count the first actual display of a coach nudge."""

    now = datetime.now()
    stats = await _get_or_create_stats(
        db,
        user_id,
        skill_id=str(nudge.skill_id or ""),
        channel=str(nudge.channel or ""),
        event_type=await _event_type_for_nudge(db, user_id, nudge),
    )
    stats.shown_count = int(stats.shown_count or 0) + 1
    stats.last_shown_at = now
    stats.updated_at = now
    await db.flush()
    return coach_skill_stats_to_dict(stats)


async def record_skill_feedback(
    db: AsyncSession,
    user_id: int,
    nudge: CoachNudge,
    outcome: str,
) -> dict[str, Any]:
    """Aggregate feedback outcomes into durable policy learning signals."""

    outcome = str(outcome or "").strip()
    now = datetime.now()
    stats = await _get_or_create_stats(
        db,
        user_id,
        skill_id=str(nudge.skill_id or ""),
        channel=str(nudge.channel or ""),
        event_type=await _event_type_for_nudge(db, user_id, nudge),
    )

    column = OUTCOME_COLUMNS.get(outcome)
    if column:
        setattr(stats, column, int(getattr(stats, column) or 0) + 1)

    if outcome in POSITIVE_OUTCOMES:
        stats.last_positive_at = now
        _apply_score(stats, 1.0 if outcome != "completed" else 1.5, now)
    elif outcome in NEGATIVE_OUTCOMES:
        stats.last_negative_at = now
        _apply_score(stats, -1.0 if outcome != "too_disruptive" else -1.5, now)
    elif outcome in SNOOZE_OUTCOMES:
        stats.last_negative_at = now
        _apply_score(stats, -0.5, now)
    else:
        stats.updated_at = now

    await db.flush()
    return coach_skill_stats_to_dict(stats)


async def list_skill_stats(db: AsyncSession, user_id: int, limit: int = 100) -> list[dict[str, Any]]:
    result = await db.execute(
        select(CoachSkillStats)
        .where(CoachSkillStats.user_id == user_id)
        .order_by(CoachSkillStats.updated_at.desc())
        .limit(max(1, min(int(limit or 100), 200)))
    )
    return [coach_skill_stats_to_dict(row) for row in result.scalars().all()]


async def get_policy_skill_stats(db: AsyncSession, user_id: int) -> list[dict[str, Any]]:
    """Return a compact stats snapshot for pure policy evaluation."""

    return await list_skill_stats(db, user_id, limit=200)
