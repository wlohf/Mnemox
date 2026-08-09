"""Durable, replayable learner-state projection outbox.

Rows are written in the same SQLAlchemy transaction as their source learning
event. Processing is deliberately small and deterministic: the worker reads a
user-owned event, projects linked evidence, and marks the row only after the
projection has flushed successfully.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import and_, func, or_, select, text, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.concept import Concept, ConceptLink
from app.models.learner_model import ProjectionOutbox
from app.models.learning_event import LearningEvent
from app.services.learner_model_service import record_evidence, record_review_result_evidence

OUTBOX_MODEL_VERSION = "projection-outbox-v1"
REPLAY_PAGE_SIZE = 200
# PostgreSQL transaction advisory-lock namespace for user-scoped projection
# batches. It is distinct from the session-level migration lock namespace.
POSTGRES_PROJECTION_LOCK_NAMESPACE = 0x4D4E4F58


def _now() -> datetime:
    return datetime.now()


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.astimezone().replace(tzinfo=None) if parsed.tzinfo else parsed
    except (TypeError, ValueError):
        return None


def outbox_to_dict(row: ProjectionOutbox) -> dict[str, Any]:
    return {
        "id": row.id,
        "user_id": row.user_id,
        "concept_id": row.concept_id,
        "source_event_id": row.source_event_id,
        "idempotency_key": row.idempotency_key,
        "projection_type": row.projection_type,
        "model_version": row.model_version,
        "payload_version": row.payload_version,
        "payload": row.payload or {},
        "occurred_at": _iso(row.occurred_at),
        "status": row.status,
        "attempts": row.attempts,
        "available_at": _iso(row.available_at),
        "locked_at": _iso(row.locked_at),
        "processed_at": _iso(row.processed_at),
        "last_error": row.last_error,
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
    }


async def enqueue_projection(
    db: AsyncSession,
    user_id: int,
    source_event_id: int,
    *,
    concept_id: int | None = None,
    projection_type: str = "learner_state",
    idempotency_key: str | None = None,
    payload: dict[str, Any] | None = None,
    model_version: str = OUTBOX_MODEL_VERSION,
    occurred_at: datetime | None = None,
) -> dict[str, Any]:
    """Insert (or return) one outbox command, scoped to its owner."""
    event = await db.scalar(
        select(LearningEvent).where(LearningEvent.id == int(source_event_id), LearningEvent.user_id == int(user_id))
    )
    if event is None:
        raise LookupError("来源学习事件不存在")
    if concept_id is not None:
        owned = await db.scalar(select(Concept.id).where(Concept.id == int(concept_id), Concept.user_id == int(user_id)))
        if owned is None:
            raise LookupError("概念不存在")
    key = (idempotency_key or f"{projection_type}:{int(source_event_id)}:{int(concept_id) if concept_id is not None else '*'}")[:200]
    values = {
        "user_id": int(user_id),
        "concept_id": int(concept_id) if concept_id is not None else None,
        "source_event_id": int(source_event_id),
        "idempotency_key": key,
        "projection_type": str(projection_type)[:60],
        "model_version": str(model_version or OUTBOX_MODEL_VERSION)[:50],
        "payload_version": 1,
        "payload": dict(payload or {}),
        "occurred_at": occurred_at or event.timestamp or _now(),
        "status": "pending",
        "attempts": 0,
        "available_at": occurred_at or _now(),
    }
    dialect_name = db.bind.dialect.name if db.bind is not None else ""
    if dialect_name == "postgresql":
        statement = postgresql_insert(ProjectionOutbox).values(**values).on_conflict_do_nothing(
            constraint="uq_projection_outbox_user_key"
        )
    elif dialect_name == "sqlite":
        statement = sqlite_insert(ProjectionOutbox).values(**values).on_conflict_do_nothing(
            index_elements=["user_id", "idempotency_key"]
        )
    else:
        # Production and local development use PostgreSQL and SQLite. Keeping
        # the fallback explicit makes unsupported dialects fail at the unique
        # constraint instead of silently weakening the idempotency contract.
        statement = ProjectionOutbox.__table__.insert().values(**values)
    await db.execute(statement)
    row = await db.scalar(
        select(ProjectionOutbox).where(
            ProjectionOutbox.user_id == int(user_id),
            ProjectionOutbox.idempotency_key == key,
        )
    )
    if row is None:
        raise RuntimeError("outbox enqueue did not produce a readable row")
    return outbox_to_dict(row)


async def enqueue_for_learning_event(
    db: AsyncSession,
    event: LearningEvent | dict[str, Any],
    *,
    concept_id: int | None = None,
) -> dict[str, Any]:
    event_id = int(event["id"] if isinstance(event, dict) else event.id)
    user_id = int(event["user_id"] if isinstance(event, dict) else event.user_id)
    event_type = str(event["event_type"] if isinstance(event, dict) else event.event_type)
    event_payload = dict(event.get("payload") or event.get("event_data") or {}) if isinstance(event, dict) else dict(event.event_data or {})
    if concept_id is None:
        candidate = event_payload.get("concept_id")
        if isinstance(candidate, int) and candidate > 0:
            # Invalid/cross-user payload references are deliberately ignored;
            # the event remains durable and can be replayed after correction.
            owned = await db.scalar(
                select(Concept.id).where(
                    Concept.id == candidate,
                    Concept.user_id == user_id,
                )
            )
            if owned is not None:
                concept_id = int(candidate)
    return await enqueue_projection(
        db, user_id, event_id, concept_id=concept_id,
        idempotency_key=f"learner_state:{event_id}:{concept_id if concept_id is not None else '*'}",
        payload={"event_type": event_type, "concept_id": concept_id},
        occurred_at=(event.get("timestamp") if isinstance(event, dict) and isinstance(event.get("timestamp"), datetime) else (event.timestamp if not isinstance(event, dict) else None)),
    )


async def _project_event(
    db: AsyncSession,
    row: ProjectionOutbox,
    *,
    event: LearningEvent | None = None,
) -> int:
    if event is None:
        event = await db.scalar(
            select(LearningEvent).where(
                LearningEvent.id == row.source_event_id,
                LearningEvent.user_id == row.user_id,
            )
        )
    if event is None:
        raise LookupError("source event was deleted")
    payload = dict(event.event_data or {})
    event_type = str(event.event_type or "")
    if event_type == "learner.manual_override" and row.concept_id is not None:
        active = bool(payload.get("active"))
        mastery_estimate = payload.get("mastery_estimate")
        score = (
            max(0.0, min(1.0, float(mastery_estimate) / 100.0))
            if active and mastery_estimate is not None
            else 0.0
        )
        await record_evidence(
            db,
            row.user_id,
            row.concept_id,
            "manual_override",
            score=score,
            reliability=1.0,
            source_event_id=event.id,
            source_type="manual",
            source_id=str(event.id),
            dimension="overall",
            observed_at=event.timestamp or _now(),
            payload=payload,
        )
        return 1
    quality = payload.get("quality")
    if quality is not None and event_type in {"review.completed", "review_complete"}:
        quality = max(0, min(5, int(float(quality))))
        target_type = str(payload.get("target_type") or payload.get("item_type") or "")
        target_id = payload.get("target_id") or payload.get("item_id")
        if target_type and target_id is not None:
            return await record_review_result_evidence(
                db, row.user_id, target_type=target_type, target_id=int(target_id),
                quality=quality, source_event_id=event.id, observed_at=event.timestamp or _now(),
                next_review_at=_parse_datetime(payload.get("next_due_at")), concept_id=row.concept_id,
                normalized_score=(
                    float(payload["normalized_score"])
                    if payload.get("normalized_score") is not None
                    else None
                ),
            )
    if row.concept_id is None:
        return 0
    mapping = {"practice.answer": "answer", "practice.recall": "recall", "study.duration": "study_duration", "study.frequency": "study_frequency"}
    evidence_type = mapping.get(event_type)
    if evidence_type is None:
        return 0
    raw_score = payload.get("score", payload.get("quality", 0.0))
    if evidence_type == "study_duration" and "score" not in payload:
        raw_score = min(1.0, max(0.0, float(payload.get("duration_minutes", 0.0)) / 25.0))
    score = float(raw_score)
    score = max(0.0, min(1.0, score if score <= 1 else score / 100.0))
    await record_evidence(
        db, row.user_id, row.concept_id, evidence_type, score=score, reliability=0.8,
        source_event_id=event.id, source_type=event.source or "projection",
        observed_at=event.timestamp or _now(), payload=payload,
    )
    return 1


def _is_noop_learner_state_projection(
    row: ProjectionOutbox,
    event: LearningEvent,
) -> bool:
    """Return whether a learner-state projection cannot write evidence."""
    if row.projection_type != "learner_state":
        return False
    return str(event.event_type or "") not in {
        "learner.manual_override",
        "review.completed",
        "review_complete",
        "practice.answer",
        "practice.recall",
        "study.duration",
        "study.frequency",
    }


async def _event_targets_concept(
    db: AsyncSession,
    event: LearningEvent,
    concept_id: int,
) -> bool:
    """Return whether an event explicitly belongs to one concept scope."""
    payload = dict(event.event_data or {})
    try:
        if int(payload.get("concept_id")) == int(concept_id):
            return True
    except (TypeError, ValueError):
        pass

    if str(event.event_type or "") not in {"review.completed", "review_complete"}:
        return False
    target_type = str(payload.get("target_type") or payload.get("item_type") or "").strip()
    target_id = payload.get("target_id") or payload.get("item_id")
    if not target_type or target_id is None:
        return False
    try:
        normalized_target_id = int(target_id)
    except (TypeError, ValueError):
        return False
    linked = await db.scalar(
        select(ConceptLink.id).where(
            ConceptLink.user_id == int(event.user_id),
            ConceptLink.concept_id == int(concept_id),
            ConceptLink.target_type == target_type,
            ConceptLink.target_id == normalized_target_id,
        )
    )
    return linked is not None


async def _lock_projection_users(
    db: AsyncSession,
    user_ids: list[int],
) -> None:
    """Serialize multi-row projection batches for each PostgreSQL user scope."""
    if not user_ids or db.bind is None or db.bind.dialect.name != "postgresql":
        return
    for lock_user_id in sorted({int(value) for value in user_ids}):
        await db.execute(
            text(
                "SELECT pg_advisory_xact_lock("
                "CAST(:namespace AS INTEGER), CAST(:user_id AS INTEGER))"
            ),
            {
                "namespace": POSTGRES_PROJECTION_LOCK_NAMESPACE,
                "user_id": lock_user_id,
            },
        )


async def process_outbox(
    db: AsyncSession,
    *,
    limit: int = 50,
    user_id: int | None = None,
    max_attempts: int = 5,
    now: datetime | None = None,
    outbox_ids: list[int] | None = None,
) -> dict[str, Any]:
    """Process pending and crash-stale rows; safe to call repeatedly."""
    current = now or _now()
    stale_before = current - timedelta(minutes=5)
    where = [
        or_(
            and_(ProjectionOutbox.status == "pending", ProjectionOutbox.attempts < max_attempts, ProjectionOutbox.available_at <= current),
            and_(ProjectionOutbox.status == "processing", ProjectionOutbox.attempts < max_attempts, ProjectionOutbox.locked_at < stale_before),
            and_(ProjectionOutbox.status == "failed", ProjectionOutbox.attempts < max_attempts, ProjectionOutbox.available_at <= current),
        )
    ]
    if user_id is not None:
        # Take the user lock before row claims so concurrent API/replay calls
        # cannot acquire concept locks in contradictory batch orders.
        await _lock_projection_users(db, [int(user_id)])
        where.append(ProjectionOutbox.user_id == int(user_id))
    if outbox_ids is not None:
        if not outbox_ids:
            return {"claimed": 0, "processed": 0, "failed": 0}
        where.append(ProjectionOutbox.id.in_([int(value) for value in outbox_ids]))
    rows = (
        await db.execute(
            select(ProjectionOutbox)
            .where(*where)
            .order_by(ProjectionOutbox.id.asc())
            .limit(max(1, min(int(limit), 500)))
            .with_for_update(skip_locked=True)
        )
    ).scalars().all()
    if user_id is None:
        # Global callers may contain several users. Lock their scopes in a
        # deterministic order before any projector acquires a concept row.
        await _lock_projection_users(db, [int(row.user_id) for row in rows])

    events_by_id: dict[int, LearningEvent] = {}
    if rows:
        event_rows = (
            await db.execute(
                select(LearningEvent).where(
                    LearningEvent.id.in_([int(row.source_event_id) for row in rows])
                )
            )
        ).scalars().all()
        events_by_id = {int(event.id): event for event in event_rows}

    processed = failed = 0

    # Persist all claims before entering per-row savepoints. The row locks from
    # the query above remain held for the surrounding transaction, so flushing
    # once here preserves recovery semantics without one database round trip
    # per status transition.
    for row in rows:
        row.status = "processing"
        row.attempts = int(row.attempts or 0) + 1
        row.locked_at = current
    if rows:
        await db.flush()

    try:
        for row in rows:
            try:
                event = events_by_id.get(int(row.source_event_id))
                if event is not None and int(event.user_id) != int(row.user_id):
                    event = None
                if event is not None and _is_noop_learner_state_projection(row, event):
                    row.status = "processed"
                    row.processed_at = current
                    row.last_error = None
                    processed += 1
                    continue
                async with db.begin_nested():
                    await _project_event(db, row, event=event)
                row.status = "processed"
                row.processed_at = current
                row.last_error = None
                processed += 1
            except Exception as exc:
                row.status = "failed"
                row.last_error = str(exc)[:2000]
                row.available_at = current + timedelta(seconds=min(300, 2 ** min(row.attempts, 8)))
                failed += 1
            finally:
                row.locked_at = None
    finally:
        if rows:
            await db.flush()
    return {"claimed": len(rows), "processed": processed, "failed": failed}


async def process_event_projection(
    db: AsyncSession,
    *,
    user_id: int,
    source_event_id: int,
) -> dict[str, int]:
    """Consume only one event's projection rows on the current request path."""
    outbox_ids = list(
        (
            await db.scalars(
                select(ProjectionOutbox.id)
                .where(
                    ProjectionOutbox.user_id == int(user_id),
                    ProjectionOutbox.source_event_id == int(source_event_id),
                )
                .order_by(ProjectionOutbox.id.asc())
            )
        ).all()
    )
    return await process_outbox(
        db,
        user_id=int(user_id),
        limit=max(1, len(outbox_ids)),
        outbox_ids=[int(value) for value in outbox_ids],
    )


async def replay_projections(
    db: AsyncSession,
    user_id: int,
    *,
    concept_id: int | None = None,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    reset_processed: bool = True,
) -> dict[str, Any]:
    """Queue and process a bounded, user-isolated event replay."""
    if start_at is not None and end_at is not None and start_at > end_at:
        raise ValueError("start_at 不能晚于 end_at")
    if concept_id is not None:
        owned = await db.scalar(
            select(Concept.id).where(
                Concept.id == int(concept_id),
                Concept.user_id == int(user_id),
            )
        )
        if owned is None:
            raise LookupError("概念不存在")
    predicates = [LearningEvent.user_id == int(user_id)]
    if start_at is not None:
        predicates.append(LearningEvent.timestamp >= start_at)
    if end_at is not None:
        predicates.append(LearningEvent.timestamp <= end_at)
    event_count = int(
        await db.scalar(
            select(func.count()).select_from(LearningEvent).where(*predicates)
        )
        or 0
    )
    totals = {"claimed": 0, "processed": 0, "failed": 0, "queued": 0}
    cursor_time: datetime | None = None
    cursor_id = 0

    while True:
        page_predicates = list(predicates)
        if cursor_time is not None:
            page_predicates.append(
                or_(
                    LearningEvent.timestamp > cursor_time,
                    and_(
                        LearningEvent.timestamp == cursor_time,
                        LearningEvent.id > cursor_id,
                    ),
                )
            )
        events = (
            await db.execute(
                select(LearningEvent)
                .where(*page_predicates)
                .order_by(LearningEvent.timestamp.asc(), LearningEvent.id.asc())
                .limit(REPLAY_PAGE_SIZE)
            )
        ).scalars().all()
        if not events:
            break

        selected_ids: list[int] = []
        for event in events:
            if concept_id is not None and not await _event_targets_concept(db, event, int(concept_id)):
                continue
            item = await enqueue_for_learning_event(db, event, concept_id=concept_id)
            selected_ids.append(int(item["id"]))
        if reset_processed and selected_ids:
            await db.execute(
                update(ProjectionOutbox)
                .where(
                    ProjectionOutbox.user_id == int(user_id),
                    ProjectionOutbox.id.in_(selected_ids),
                )
                .values(
                    status="pending",
                    attempts=0,
                    locked_at=None,
                    processed_at=None,
                    last_error=None,
                    available_at=_now(),
                )
            )
        page_result = await process_outbox(
            db,
            user_id=int(user_id),
            limit=REPLAY_PAGE_SIZE,
            outbox_ids=selected_ids,
        )
        totals["queued"] += len(selected_ids)
        for key in ("claimed", "processed", "failed"):
            totals[key] += int(page_result[key])

        last_event = events[-1]
        cursor_time = last_event.timestamp
        cursor_id = int(last_event.id)
        if len(events) < REPLAY_PAGE_SIZE:
            break

    totals.update(
        {
            "events": event_count,
            "user_id": int(user_id),
            "concept_id": concept_id,
        }
    )
    return totals
