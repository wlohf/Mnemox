"""Coach event recording and retrieval."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.coach import CoachEvent


def _event_to_dict(event: CoachEvent) -> dict[str, Any]:
    return {
        "id": event.id,
        "user_id": event.user_id,
        "event_type": event.event_type,
        "source": event.source,
        "severity": event.severity,
        "payload": event.payload or {},
        "dedupe_key": event.dedupe_key,
        "occurred_at": event.occurred_at.isoformat() if event.occurred_at else None,
        "created_at": event.created_at.isoformat() if event.created_at else None,
    }


async def record_coach_event(
    db: AsyncSession,
    user_id: int,
    event_type: str,
    source: str,
    payload: dict[str, Any] | None = None,
    severity: str = "info",
    *,
    dedupe_key: str | None = None,
    occurred_at: datetime | None = None,
) -> dict[str, Any]:
    """Record a normalized event, returning an existing recent one for a dedupe key."""

    now = occurred_at or datetime.now()
    event_type = str(event_type or "").strip()[:100]
    source = str(source or "unknown").strip()[:50] or "unknown"
    severity = str(severity or "info").strip()[:20] or "info"
    if not event_type:
        raise ValueError("event_type 不能为空")

    if dedupe_key:
        cutoff = now - timedelta(hours=6)
        result = await db.execute(
            select(CoachEvent)
            .where(
                CoachEvent.user_id == user_id,
                CoachEvent.event_type == event_type,
                CoachEvent.dedupe_key == dedupe_key[:160],
                CoachEvent.occurred_at >= cutoff,
            )
            .order_by(CoachEvent.occurred_at.desc())
            .limit(1)
        )
        existing = result.scalar_one_or_none()
        if existing:
            return _event_to_dict(existing)

    event = CoachEvent(
        id=f"ce_{uuid4().hex[:24]}",
        user_id=user_id,
        event_type=event_type,
        source=source,
        severity=severity,
        payload=payload or {},
        dedupe_key=dedupe_key[:160] if dedupe_key else None,
        occurred_at=now,
    )
    db.add(event)
    await db.flush()
    await db.refresh(event)
    return _event_to_dict(event)


async def get_coach_event(db: AsyncSession, user_id: int, event_id: str) -> dict[str, Any] | None:
    result = await db.execute(select(CoachEvent).where(CoachEvent.id == event_id, CoachEvent.user_id == user_id))
    row = result.scalar_one_or_none()
    return _event_to_dict(row) if row else None


async def list_recent_coach_events(db: AsyncSession, user_id: int, limit: int = 50) -> list[dict[str, Any]]:
    result = await db.execute(
        select(CoachEvent)
        .where(CoachEvent.user_id == user_id)
        .order_by(CoachEvent.occurred_at.desc(), CoachEvent.created_at.desc())
        .limit(max(1, min(int(limit or 50), 100)))
    )
    return [_event_to_dict(row) for row in result.scalars().all()]
