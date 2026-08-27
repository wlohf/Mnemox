"""Normalized learning event recording for Agent and Coach memory pipelines."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.learning_event import EventCategory, LearningEvent


EVENT_SCHEMA_VERSION = 1


class CanonicalEventType:
    """Event names whose payloads are part of the metrics contract."""

    POMODORO_STARTED = "pomodoro.started"
    POMODORO_COMPLETED = "pomodoro.completed"
    POMODORO_INTERRUPTED = "pomodoro.interrupted"
    REVIEW_SCHEDULED = "review.scheduled"
    REVIEW_COMPLETED = "review.completed"
    COACH_NUDGE_CREATED = "coach.nudge.created"
    COACH_NUDGE_SHOWN = "coach.nudge.shown"
    COACH_NUDGE_ACCEPTED = "coach.nudge.accepted"
    COACH_NUDGE_STARTED = "coach.nudge.started"
    COACH_NUDGE_COMPLETED = "coach.nudge.completed"
    COACH_NUDGE_ABANDONED = "coach.nudge.abandoned"
    COACH_NUDGE_EXPIRED = "coach.nudge.expired"
    COACH_NUDGE_SNOOZED = "coach.nudge.snoozed"
    COACH_NUDGE_DISMISSED = "coach.nudge.dismissed"
    COACH_NUDGE_FEEDBACK = "coach.nudge.feedback"


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


async def _ensure_projection_outbox(db: AsyncSession, event: LearningEvent) -> None:
    # Lazy import avoids a module cycle: the projection handler depends on the
    # normalized event and learner-model services.
    from app.services.projection_outbox_service import enqueue_for_learning_event

    await enqueue_for_learning_event(db, event)


async def _find_deduped_event(
    db: AsyncSession,
    *,
    user_id: int,
    event_type: str,
    dedupe_key: str,
) -> LearningEvent | None:
    return await db.scalar(
        select(LearningEvent)
        .where(
            LearningEvent.user_id == int(user_id),
            LearningEvent.event_type == event_type,
            LearningEvent.dedupe_key == dedupe_key,
        )
        .order_by(LearningEvent.id.asc())
        .limit(1)
    )


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
    event_category: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Record one user-scoped learning event, returning an existing row on dedupe."""

    normalized_type = normalize_learning_event_type(event_type)[:50]
    clean_source = str(source or "unknown").strip()[:50] or "unknown"
    clean_dedupe = str(dedupe_key or "").strip()[:160] or None
    timestamp = occurred_at or datetime.now()

    if clean_dedupe:
        existing = await _find_deduped_event(
            db,
            user_id=int(user_id),
            event_type=normalized_type,
            dedupe_key=clean_dedupe,
        )
        if existing:
            await _ensure_projection_outbox(db, existing)
            return learning_event_to_dict(existing)

    data = dict(payload or {})
    event_metadata = dict(metadata or {})
    event_metadata.setdefault("schema_version", EVENT_SCHEMA_VERSION)
    event = LearningEvent(
        user_id=user_id,
        event_type=normalized_type,
        event_category=event_category or _event_category_for(normalized_type),
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
        extra_metadata=event_metadata,
    )
    if clean_dedupe:
        try:
            # The unique index is the concurrent source of truth. A savepoint
            # isolates a lost insert race without rolling back the domain
            # mutation in the caller's transaction.
            async with db.begin_nested():
                db.add(event)
                await db.flush()
                await db.refresh(event)
        except IntegrityError:
            existing = await _find_deduped_event(
                db,
                user_id=int(user_id),
                event_type=normalized_type,
                dedupe_key=clean_dedupe,
            )
            if existing is None:
                raise
            await _ensure_projection_outbox(db, existing)
            return learning_event_to_dict(existing)
    else:
        db.add(event)
        await db.flush()
        await db.refresh(event)
    # This happens before the caller commits, so the event and outbox cannot
    # become durable independently.
    await _ensure_projection_outbox(db, event)
    return learning_event_to_dict(event)


def _event_value(source: Any, name: str, default: Any = None) -> Any:
    """Read an ORM object or a dict without coupling the event layer to Coach."""

    if isinstance(source, dict):
        return source.get(name, default)
    return getattr(source, name, default)


async def record_coach_nudge_event(
    db: AsyncSession,
    user_id: int,
    nudge: Any,
    event_type: str,
    *,
    outcome: str | None = None,
    attribution: dict[str, Any] | None = None,
    occurred_at: datetime | None = None,
) -> dict[str, Any]:
    """Append a privacy-minimized Coach lifecycle event to the common ledger."""

    normalized_type = normalize_learning_event_type(event_type)
    nudge_id = str(_event_value(nudge, "id", "") or "").strip()
    if not nudge_id:
        raise ValueError("Coach nudge 必须有 id 才能记录生命周期事件")

    suggested_action = _event_value(nudge, "suggested_action", {}) or {}
    payload = {
        "nudge_id": nudge_id,
        "trigger_event_id": _event_value(nudge, "event_id"),
        "skill_id": str(_event_value(nudge, "skill_id", "") or ""),
        "channel": str(_event_value(nudge, "channel", "") or ""),
        "priority": str(_event_value(nudge, "priority", "") or ""),
        "actionable": bool(suggested_action),
        "requires_confirmation": bool(_event_value(nudge, "requires_confirmation", False)),
    }
    if outcome:
        payload["outcome"] = str(outcome)[:40]
    if attribution:
        # Keep lifecycle events useful for replay without copying free-form
        # notes, content, or arbitrary client payloads into the common ledger.
        safe_attribution: dict[str, Any] = {}
        for key in ("method", "attempt_id", "action_type", "linked_event_id", "linked_event_type", "reason"):
            value = attribution.get(key)
            if value is None or value == "":
                continue
            if key == "linked_event_id":
                try:
                    safe_attribution[key] = int(value)
                except (TypeError, ValueError):
                    continue
            else:
                safe_attribution[key] = str(value)[:120]
        if safe_attribution:
            payload["attribution"] = safe_attribution

    dedupe_suffix = str(outcome or "")[:40]
    return await record_learning_event(
        db,
        user_id,
        normalized_type,
        source="coach",
        payload=payload,
        dedupe_key=f"{normalized_type}:{nudge_id}:{dedupe_suffix}",
        occurred_at=occurred_at,
        metadata={
            "schema_version": EVENT_SCHEMA_VERSION,
            "nudge_id": nudge_id,
            "trigger_event_id": _event_value(nudge, "event_id"),
            "attempt_id": (payload.get("attribution") or {}).get("attempt_id"),
        },
    )


async def record_review_scheduled_event(
    db: AsyncSession,
    user_id: int,
    *,
    entity_type: str,
    entity_id: int,
    due_at: datetime,
    source: str,
    item_type: str | None = None,
    item_id: int | None = None,
    reason: str | None = None,
    occurred_at: datetime | None = None,
) -> dict[str, Any]:
    """Record one review opportunity; its stable key is used for on-time metrics."""

    review_key = f"{entity_type}:{int(entity_id)}"
    scheduled_for = _to_iso(due_at)
    payload = {
        "review_key": review_key,
        "entity_type": str(entity_type)[:40],
        "entity_id": int(entity_id),
        "scheduled_for": scheduled_for,
        "item_type": str(item_type or "")[:40],
        "item_id": item_id,
        "reason": str(reason or "")[:40],
    }
    return await record_learning_event(
        db,
        user_id,
        CanonicalEventType.REVIEW_SCHEDULED,
        source=source,
        payload=payload,
        dedupe_key=f"review.scheduled:{review_key}:{scheduled_for}",
        occurred_at=occurred_at,
        metadata={"schema_version": EVENT_SCHEMA_VERSION, "review_key": review_key},
    )


async def record_review_completed_event(
    db: AsyncSession,
    user_id: int,
    *,
    entity_type: str,
    entity_id: int,
    scheduled_for: datetime,
    source: str,
    quality: int | None = None,
    item_type: str | None = None,
    item_id: int | None = None,
    next_due_at: datetime | None = None,
    scheduler: str | None = None,
    concept_id: int | None = None,
    normalized_score: float | None = None,
    occurred_at: datetime | None = None,
) -> dict[str, Any]:
    """Record a completed review against the opportunity that was due."""

    review_key = f"{entity_type}:{int(entity_id)}"
    scheduled_for_iso = _to_iso(scheduled_for)
    payload = {
        "review_key": review_key,
        "entity_type": str(entity_type)[:40],
        "entity_id": int(entity_id),
        "scheduled_for": scheduled_for_iso,
        "item_type": str(item_type or "")[:40],
        "item_id": item_id,
        "quality": quality,
        "next_due_at": _to_iso(next_due_at),
        "scheduler": str(scheduler or "")[:20],
        "concept_id": int(concept_id) if concept_id is not None else None,
        "normalized_score": (
            float(normalized_score) if normalized_score is not None else None
        ),
    }
    return await record_learning_event(
        db,
        user_id,
        CanonicalEventType.REVIEW_COMPLETED,
        source=source,
        payload=payload,
        dedupe_key=f"review.completed:{review_key}:{scheduled_for_iso}",
        occurred_at=occurred_at,
        metadata={"schema_version": EVENT_SCHEMA_VERSION, "review_key": review_key},
    )


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
