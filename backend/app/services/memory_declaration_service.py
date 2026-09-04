"""Canonical, auditable declarations for user-controlled memories."""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy import delete, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.memory import MemoryDeclaration, UserMemory
from app.utils.utc import to_db_utc, to_utc_iso, utc_now_db


MANUAL_DECLARATION_VERSION = "manual-memory-declaration-v1"
AUTOMATIC_DECLARATION_VERSION = "automatic-memory-declaration-v1"
ACTIVE_DECLARATION_STATUSES = ("confirmed", "staged")
REJECTED_DECLARATION_STATUSES = ("ignored", "inaccurate")
EXPIRED_DECLARATION_STATUS = "expired"
SUPERSEDED_DECLARATION_STATUS = "superseded"
DERIVED_PROFILE_KEY = "agent_core_profile"
_EVIDENCE_KEYS = frozenset(
    {
        "kind",
        "event_id",
        "event_type",
        "event_count",
        "conversation_id",
        "material_id",
        "note_id",
        "goal_id",
        "task_id",
        "timestamp",
        "category",
        "count",
        "top_event_type",
        "duration_seconds",
    }
)


def _clamp_confidence(value: float | None) -> float:
    try:
        return max(0.0, min(1.0, float(value if value is not None else 0.8)))
    except (TypeError, ValueError):
        return 0.8


def memory_fact_key(memory: UserMemory) -> str:
    """Use the stable memory key, not its broad category, as fact identity."""
    return str(memory.memory_key or "").strip()[:100]


def _same_fact_value(left: str | None, right: str | None) -> bool:
    return " ".join(str(left or "").split()).casefold() == " ".join(
        str(right or "").split()
    ).casefold()


def _resolution_reason(reason: str | None, fallback: str) -> str:
    compact = " ".join(str(reason or fallback).split())
    return compact[:255] or fallback


async def _current_fact_declaration(
    db: AsyncSession,
    *,
    user_id: int,
    fact_key: str,
    exclude_declaration_id: int | None = None,
) -> MemoryDeclaration | None:
    conditions = [
        MemoryDeclaration.user_id == user_id,
        MemoryDeclaration.fact_key == fact_key,
        MemoryDeclaration.review_status == "confirmed",
        MemoryDeclaration.valid_to.is_(None),
        UserMemory.user_id == user_id,
        UserMemory.status == "active",
        UserMemory.review_status == "confirmed",
        or_(UserMemory.expires_at.is_(None), UserMemory.expires_at > utc_now_db()),
    ]
    if exclude_declaration_id is not None:
        conditions.append(MemoryDeclaration.id != exclude_declaration_id)
    result = await db.execute(
        select(MemoryDeclaration)
        .join(UserMemory, UserMemory.id == MemoryDeclaration.memory_id)
        .where(*conditions)
        .order_by(UserMemory.is_locked.desc(), MemoryDeclaration.observed_at.desc(), MemoryDeclaration.id.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def invalidate_derived_memory_profiles(
    db: AsyncSession,
    *,
    user_id: int,
    memory_ids: set[int],
) -> int:
    """Remove profile projections that still contain changed or deleted facts."""
    if not memory_ids:
        return 0
    result = await db.execute(
        select(UserMemory).where(
            UserMemory.user_id == user_id,
            UserMemory.memory_key == DERIVED_PROFILE_KEY,
        )
    )
    removed = 0
    for profile in result.scalars().all():
        payload = _decode_evidence(profile.memory_value)
        if not isinstance(payload, dict):
            continue
        source_ids: set[int] = set()
        for source_id in payload.get("source_memory_ids") or []:
            try:
                source_ids.add(int(source_id))
            except (TypeError, ValueError):
                continue
        if not source_ids.intersection(memory_ids):
            continue
        await db.delete(profile)
        removed += 1
    if removed:
        await db.flush()
    return removed


async def record_manual_memory_declaration(
    db: AsyncSession,
    *,
    memory: UserMemory,
    user_id: int,
    observed_at: datetime | None = None,
    correction_reason: str | None = None,
) -> MemoryDeclaration:
    """Append a user declaration and close the prior current declaration.

    This function deliberately does not mutate ``UserMemory``. Callers update
    the current projection first, then record the declaration in the same
    transaction so the effective value and its provenance stay atomic.
    """
    now = to_db_utc(observed_at) if observed_at is not None else utc_now_db()
    fact_key = memory_fact_key(memory)
    prior_result = await db.execute(
        select(MemoryDeclaration)
        .where(
            MemoryDeclaration.user_id == user_id,
            or_(
                MemoryDeclaration.fact_key == fact_key,
                MemoryDeclaration.memory_id == memory.id,
            ),
            MemoryDeclaration.review_status.in_(ACTIVE_DECLARATION_STATUSES),
            MemoryDeclaration.valid_to.is_(None),
        )
        .order_by(MemoryDeclaration.review_status.asc(), MemoryDeclaration.id.desc())
    )
    prior_rows = list(prior_result.scalars().all())
    confirmed_prior = next((row for row in prior_rows if row.review_status == "confirmed"), None)
    prior = confirmed_prior or (prior_rows[0] if prior_rows else None)
    affected_ids = {int(memory.id)}
    reason = _resolution_reason(correction_reason, "user_correction" if prior else "user_declaration")
    for previous in prior_rows:
        previous.review_status = SUPERSEDED_DECLARATION_STATUS
        previous.valid_to = now
        previous.resolution_reason = reason
        if previous.memory_id != memory.id:
            projection_result = await db.execute(
                select(UserMemory).where(
                    UserMemory.id == previous.memory_id,
                    UserMemory.user_id == user_id,
                )
            )
            projection = projection_result.scalar_one_or_none()
            if projection:
                projection.status = SUPERSEDED_DECLARATION_STATUS
                projection.review_status = SUPERSEDED_DECLARATION_STATUS
                projection.last_seen_at = now
                affected_ids.add(int(projection.id))

    declaration = MemoryDeclaration(
        user_id=user_id,
        memory_id=memory.id,
        subject=f"user:{user_id}",
        predicate=(memory.category or "preference")[:80],
        fact_key=fact_key,
        value=memory.memory_value,
        valid_from=now,
        observed_at=now,
        confidence=_clamp_confidence(memory.confidence),
        review_status="confirmed",
        source_type="manual",
        source_id=f"memory:{memory.id}",
        evidence=json.dumps(
            {
                "kind": "manual_memory_correction" if prior else "manual_memory_declaration",
                "memory_id": memory.id,
                **({"correction_reason": reason} if prior and correction_reason else {}),
            },
            ensure_ascii=False,
        ),
        created_by="user",
        model_version=MANUAL_DECLARATION_VERSION,
        supersedes_id=prior.id if prior else None,
        resolution_reason=reason if correction_reason else None,
    )
    db.add(declaration)
    await db.flush()
    if prior:
        await invalidate_derived_memory_profiles(db, user_id=user_id, memory_ids=affected_ids)
    return declaration


def _decode_evidence(value: str | None) -> Any:
    if not value:
        return None
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return None


def _safe_evidence_summary(value: str | None) -> Any:
    """Keep provenance identifiers while preventing raw conversation copies."""
    parsed = _decode_evidence(value)

    def _clean(item: Any) -> Any:
        if isinstance(item, list):
            return [_clean(child) for child in item if isinstance(child, (dict, list))]
        if not isinstance(item, dict):
            return None
        return {
            key: item[key]
            for key in _EVIDENCE_KEYS
            if key in item and item[key] is not None
        }

    cleaned = _clean(parsed)
    if cleaned is None:
        return []
    return cleaned


def _source_event_id(source_type: str, source_id: str | None, evidence: Any) -> int | None:
    """Resolve an event identifier only when the stored provenance proves it."""
    candidates: list[Any] = []
    if source_type == "learning_event":
        candidates.append(source_id)
    if isinstance(evidence, dict):
        candidates.append(evidence.get("event_id"))
    elif isinstance(evidence, list):
        candidates.extend(
            item.get("event_id") for item in evidence if isinstance(item, dict)
        )
    for candidate in candidates:
        try:
            if candidate is not None:
                return int(candidate)
        except (TypeError, ValueError):
            continue
    return None


def _same_automatic_declaration(
    declaration: MemoryDeclaration,
    *,
    memory: UserMemory,
    source_type: str,
    source_id: str | None,
    evidence: Any,
    review_status: str,
    created_by: str,
    model_version: str,
) -> bool:
    return (
        declaration.value == memory.memory_value
        and declaration.fact_key == memory_fact_key(memory)
        and declaration.predicate == (memory.category or "preference")[:80]
        and _clamp_confidence(declaration.confidence) == _clamp_confidence(memory.confidence)
        and declaration.review_status == review_status
        and declaration.source_type == source_type
        and declaration.source_id == source_id
        and _decode_evidence(declaration.evidence) == evidence
        and declaration.created_by == created_by
        and declaration.model_version == model_version
    )


async def record_automatic_memory_declaration(
    db: AsyncSession,
    *,
    memory: UserMemory,
    user_id: int,
    created_by: str,
    model_version: str = AUTOMATIC_DECLARATION_VERSION,
    observed_at: datetime | None = None,
) -> MemoryDeclaration:
    """Append a source-safe declaration for an automatic memory projection.

    Identical retries reuse the open declaration; a meaningful automatic update
    closes its predecessor before persisting the new state. Manual corrections
    are protected by the caller's lock checks and therefore never arrive here.
    """
    now = to_db_utc(observed_at) if observed_at is not None else utc_now_db()
    fact_key = memory_fact_key(memory)
    source_type = (memory.source_type or "automatic")[:50]
    source_id = (memory.source_id or None)
    review_status = (memory.review_status or "staged")[:20]
    evidence = _safe_evidence_summary(memory.evidence)
    prior_result = await db.execute(
        select(MemoryDeclaration)
        .where(
            MemoryDeclaration.user_id == user_id,
            MemoryDeclaration.memory_id == memory.id,
            MemoryDeclaration.review_status.in_(ACTIVE_DECLARATION_STATUSES),
            MemoryDeclaration.valid_to.is_(None),
        )
        .order_by(MemoryDeclaration.id.desc())
        .limit(1)
    )
    prior = prior_result.scalar_one_or_none()
    current = await _current_fact_declaration(db, user_id=user_id, fact_key=fact_key)
    conflict = (
        current
        if current
        and current.memory_id != memory.id
        and not _same_fact_value(current.value, memory.memory_value)
        else None
    )
    if conflict and review_status == "confirmed":
        memory.status = "staged"
        memory.review_status = "staged"
        review_status = "staged"
    if prior and _same_automatic_declaration(
        prior,
        memory=memory,
        source_type=source_type,
        source_id=source_id,
        evidence=evidence,
        review_status=review_status,
        created_by=created_by,
        model_version=model_version,
    ):
        if prior.review_status == "staged":
            prior.conflicts_with_id = conflict.id if conflict else None
        return prior
    if prior:
        prior.review_status = SUPERSEDED_DECLARATION_STATUS
        prior.valid_to = now
        prior.resolution_reason = "newer_observation"

    declaration = MemoryDeclaration(
        user_id=user_id,
        memory_id=memory.id,
        subject=f"user:{user_id}",
        predicate=(memory.category or "preference")[:80],
        fact_key=fact_key,
        value=memory.memory_value,
        valid_from=now,
        observed_at=now,
        confidence=_clamp_confidence(memory.confidence),
        review_status=review_status,
        source_event_id=_source_event_id(source_type, source_id, evidence),
        source_type=source_type,
        source_id=source_id,
        evidence=json.dumps(evidence, ensure_ascii=False, sort_keys=True),
        created_by=created_by[:30],
        model_version=model_version[:80],
        supersedes_id=prior.id if prior else None,
        conflicts_with_id=conflict.id if conflict else None,
    )
    db.add(declaration)
    await db.flush()
    return declaration


async def sync_memory_declaration_review_status(
    db: AsyncSession,
    *,
    user_id: int,
    memory_id: int,
    review_status: str,
    reviewed_at: datetime | None = None,
    resolution_reason: str | None = None,
) -> MemoryDeclaration | None:
    """Synchronize a candidate's user review without inventing a new claim."""
    if review_status not in {"confirmed", *REJECTED_DECLARATION_STATUSES}:
        raise ValueError("Unsupported declaration review status")
    result = await db.execute(
        select(MemoryDeclaration)
        .where(
            MemoryDeclaration.user_id == user_id,
            MemoryDeclaration.memory_id == memory_id,
            MemoryDeclaration.review_status.in_(ACTIVE_DECLARATION_STATUSES),
        )
        .order_by(MemoryDeclaration.id.desc())
        .limit(1)
    )
    declaration = result.scalar_one_or_none()
    if not declaration:
        return None
    now = to_db_utc(reviewed_at) if reviewed_at is not None else utc_now_db()
    affected_ids: set[int] = set()
    if review_status == "confirmed":
        current = await _current_fact_declaration(
            db,
            user_id=user_id,
            fact_key=declaration.fact_key,
            exclude_declaration_id=declaration.id,
        )
        if current:
            current.review_status = SUPERSEDED_DECLARATION_STATUS
            current.valid_to = now
            current.resolution_reason = _resolution_reason(resolution_reason, "user_confirmed_replacement")
            declaration.supersedes_id = current.id
            if current.memory_id != memory_id:
                projection_result = await db.execute(
                    select(UserMemory).where(
                        UserMemory.id == current.memory_id,
                        UserMemory.user_id == user_id,
                    )
                )
                projection = projection_result.scalar_one_or_none()
                if projection:
                    projection.status = SUPERSEDED_DECLARATION_STATUS
                    projection.review_status = SUPERSEDED_DECLARATION_STATUS
                    projection.last_seen_at = now
                    affected_ids.add(int(projection.id))
        declaration.valid_from = now
        declaration.valid_to = None
        declaration.resolution_reason = _resolution_reason(
            resolution_reason,
            "user_confirmed_replacement" if current else "user_confirmed",
        )
    declaration.review_status = review_status
    if review_status in REJECTED_DECLARATION_STATUSES:
        declaration.valid_to = now
        declaration.resolution_reason = _resolution_reason(resolution_reason, f"user_marked_{review_status}")
    if affected_ids:
        await invalidate_derived_memory_profiles(db, user_id=user_id, memory_ids=affected_ids)
    return declaration


async def expire_memory_facts(
    db: AsyncSession,
    *,
    user_id: int,
    observed_at: datetime | None = None,
) -> list[int]:
    """Close overdue projections and their canonical declarations atomically."""
    now = to_db_utc(observed_at) if observed_at is not None else utc_now_db()
    result = await db.execute(
        select(UserMemory).where(
            UserMemory.user_id == user_id,
            UserMemory.expires_at.is_not(None),
            UserMemory.expires_at <= now,
            UserMemory.status.in_(("active", "staged")),
        )
    )
    rows = list(result.scalars().all())
    if not rows:
        return []
    expired_ids: set[int] = set()
    for memory in rows:
        effective_end = memory.expires_at or now
        memory.status = EXPIRED_DECLARATION_STATUS
        memory.review_status = EXPIRED_DECLARATION_STATUS
        memory.last_seen_at = now
        expired_ids.add(int(memory.id))
        declarations_result = await db.execute(
            select(MemoryDeclaration).where(
                MemoryDeclaration.user_id == user_id,
                MemoryDeclaration.memory_id == memory.id,
                MemoryDeclaration.review_status.in_(ACTIVE_DECLARATION_STATUSES),
                MemoryDeclaration.valid_to.is_(None),
            )
        )
        for declaration in declarations_result.scalars().all():
            declaration.review_status = EXPIRED_DECLARATION_STATUS
            declaration.valid_to = max(declaration.valid_from, effective_end)
            declaration.resolution_reason = "expired_at_configured_deadline"
    await db.flush()
    await invalidate_derived_memory_profiles(db, user_id=user_id, memory_ids=expired_ids)
    return sorted(expired_ids)


async def list_memory_conflicts(
    db: AsyncSession,
    *,
    user_id: int,
) -> list[dict[str, Any]]:
    """Return staged contradictions without exposing another user's claims."""
    result = await db.execute(
        select(MemoryDeclaration)
        .join(UserMemory, UserMemory.id == MemoryDeclaration.memory_id)
        .where(
            MemoryDeclaration.user_id == user_id,
            MemoryDeclaration.review_status == "staged",
            MemoryDeclaration.valid_to.is_(None),
            MemoryDeclaration.conflicts_with_id.is_not(None),
            UserMemory.user_id == user_id,
            UserMemory.review_status == "staged",
            UserMemory.status.in_(("active", "staged")),
        )
        .order_by(MemoryDeclaration.observed_at.desc(), MemoryDeclaration.id.desc())
    )
    conflicts: list[dict[str, Any]] = []
    for candidate in result.scalars().all():
        current_result = await db.execute(
            select(MemoryDeclaration).where(
                MemoryDeclaration.id == candidate.conflicts_with_id,
                MemoryDeclaration.user_id == user_id,
                MemoryDeclaration.fact_key == candidate.fact_key,
                MemoryDeclaration.review_status == "confirmed",
                MemoryDeclaration.valid_to.is_(None),
            )
        )
        current = current_result.scalar_one_or_none()
        if not current:
            continue
        conflicts.append(
            {
                "fact_key": candidate.fact_key,
                "candidate_memory_id": candidate.memory_id,
                "current_memory_id": current.memory_id,
                "candidate": declaration_to_dict(candidate),
                "current": declaration_to_dict(current),
            }
        )
    return conflicts


def declaration_to_dict(declaration: MemoryDeclaration) -> dict[str, Any]:
    """Return a stable JSON-safe declaration representation for the UI."""
    return {
        "id": declaration.id,
        "memory_id": declaration.memory_id,
        "subject": declaration.subject,
        "predicate": declaration.predicate,
        "fact_key": declaration.fact_key,
        "value": declaration.value,
        "valid_from": to_utc_iso(declaration.valid_from) if declaration.valid_from else None,
        "valid_to": to_utc_iso(declaration.valid_to) if declaration.valid_to else None,
        "observed_at": to_utc_iso(declaration.observed_at) if declaration.observed_at else None,
        "confidence": declaration.confidence,
        "review_status": declaration.review_status,
        "source_event_id": declaration.source_event_id,
        "source_type": declaration.source_type,
        "source_id": declaration.source_id,
        "evidence": _decode_evidence(declaration.evidence),
        "created_by": declaration.created_by,
        "model_version": declaration.model_version,
        "supersedes_id": declaration.supersedes_id,
        "conflicts_with_id": declaration.conflicts_with_id,
        "resolution_reason": declaration.resolution_reason,
        "created_at": to_utc_iso(declaration.created_at) if declaration.created_at else None,
    }


async def list_memory_declarations(
    db: AsyncSession,
    *,
    user_id: int,
    memory_id: int,
) -> list[dict[str, Any]]:
    memory_result = await db.execute(
        select(UserMemory.memory_key).where(
            UserMemory.id == memory_id,
            UserMemory.user_id == user_id,
        )
    )
    fact_key = str(memory_result.scalar_one_or_none() or "").strip()[:100]
    result = await db.execute(
        select(MemoryDeclaration)
        .where(
            MemoryDeclaration.user_id == user_id,
            or_(
                MemoryDeclaration.memory_id == memory_id,
                MemoryDeclaration.fact_key == fact_key,
            ) if fact_key else MemoryDeclaration.memory_id == memory_id,
        )
        .order_by(MemoryDeclaration.observed_at.desc(), MemoryDeclaration.id.desc())
    )
    return [declaration_to_dict(row) for row in result.scalars().all()]


async def delete_memory_declarations(
    db: AsyncSession,
    *,
    user_id: int,
    memory_id: int,
) -> None:
    """Explicitly remove declarations before deleting a memory projection.

    PostgreSQL and fresh SQLite installations also have a cascade FK. The
    explicit scoped delete keeps older local SQLite databases safe even before
    their foreign-key metadata has caught up.
    """
    ids_result = await db.execute(
        select(MemoryDeclaration.id).where(
            MemoryDeclaration.user_id == user_id,
            MemoryDeclaration.memory_id == memory_id,
        )
    )
    declaration_ids = [int(value) for value in ids_result.scalars().all()]
    if declaration_ids:
        await db.execute(
            update(MemoryDeclaration)
            .where(
                MemoryDeclaration.user_id == user_id,
                MemoryDeclaration.conflicts_with_id.in_(declaration_ids),
            )
            .values(conflicts_with_id=None)
        )
        await db.execute(
            update(MemoryDeclaration)
            .where(
                MemoryDeclaration.user_id == user_id,
                MemoryDeclaration.supersedes_id.in_(declaration_ids),
            )
            .values(supersedes_id=None)
        )
    await invalidate_derived_memory_profiles(db, user_id=user_id, memory_ids={int(memory_id)})
    await db.execute(
        delete(MemoryDeclaration).where(
            MemoryDeclaration.user_id == user_id,
            MemoryDeclaration.memory_id == memory_id,
        )
    )
