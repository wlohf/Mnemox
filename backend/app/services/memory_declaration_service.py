"""Canonical, auditable declarations for user-controlled memories."""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.memory import MemoryDeclaration, UserMemory


MANUAL_DECLARATION_VERSION = "manual-memory-declaration-v1"
AUTOMATIC_DECLARATION_VERSION = "automatic-memory-declaration-v1"
ACTIVE_DECLARATION_STATUSES = ("confirmed", "staged")
REJECTED_DECLARATION_STATUSES = ("ignored", "inaccurate")
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


async def record_manual_memory_declaration(
    db: AsyncSession,
    *,
    memory: UserMemory,
    user_id: int,
    observed_at: datetime | None = None,
) -> MemoryDeclaration:
    """Append a user declaration and close the prior current declaration.

    This function deliberately does not mutate ``UserMemory``. Callers update
    the current projection first, then record the declaration in the same
    transaction so the effective value and its provenance stay atomic.
    """
    now = observed_at or datetime.now()
    prior_result = await db.execute(
        select(MemoryDeclaration)
        .where(
            MemoryDeclaration.user_id == user_id,
            MemoryDeclaration.memory_id == memory.id,
            MemoryDeclaration.review_status.in_(ACTIVE_DECLARATION_STATUSES),
        )
        .order_by(MemoryDeclaration.id.desc())
        .limit(1)
    )
    prior = prior_result.scalar_one_or_none()
    if prior:
        prior.review_status = "superseded"
        prior.valid_to = now

    declaration = MemoryDeclaration(
        user_id=user_id,
        memory_id=memory.id,
        subject=f"user:{user_id}",
        predicate=(memory.category or "preference")[:80],
        value=memory.memory_value,
        valid_from=now,
        observed_at=now,
        confidence=_clamp_confidence(memory.confidence),
        review_status="confirmed",
        source_type="manual",
        source_id=f"memory:{memory.id}",
        evidence=json.dumps(
            {"kind": "manual_memory_declaration", "memory_id": memory.id},
            ensure_ascii=False,
        ),
        created_by="user",
        model_version=MANUAL_DECLARATION_VERSION,
        supersedes_id=prior.id if prior else None,
    )
    db.add(declaration)
    await db.flush()
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
    now = observed_at or datetime.now()
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
        )
        .order_by(MemoryDeclaration.id.desc())
        .limit(1)
    )
    prior = prior_result.scalar_one_or_none()
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
        return prior
    if prior:
        prior.review_status = "superseded"
        prior.valid_to = now

    declaration = MemoryDeclaration(
        user_id=user_id,
        memory_id=memory.id,
        subject=f"user:{user_id}",
        predicate=(memory.category or "preference")[:80],
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
    declaration.review_status = review_status
    if review_status in REJECTED_DECLARATION_STATUSES:
        declaration.valid_to = reviewed_at or datetime.now()
    return declaration


def declaration_to_dict(declaration: MemoryDeclaration) -> dict[str, Any]:
    """Return a stable JSON-safe declaration representation for the UI."""
    return {
        "id": declaration.id,
        "memory_id": declaration.memory_id,
        "subject": declaration.subject,
        "predicate": declaration.predicate,
        "value": declaration.value,
        "valid_from": declaration.valid_from.isoformat() if declaration.valid_from else None,
        "valid_to": declaration.valid_to.isoformat() if declaration.valid_to else None,
        "observed_at": declaration.observed_at.isoformat() if declaration.observed_at else None,
        "confidence": declaration.confidence,
        "review_status": declaration.review_status,
        "source_event_id": declaration.source_event_id,
        "source_type": declaration.source_type,
        "source_id": declaration.source_id,
        "evidence": _decode_evidence(declaration.evidence),
        "created_by": declaration.created_by,
        "model_version": declaration.model_version,
        "supersedes_id": declaration.supersedes_id,
        "created_at": declaration.created_at.isoformat() if declaration.created_at else None,
    }


async def list_memory_declarations(
    db: AsyncSession,
    *,
    user_id: int,
    memory_id: int,
) -> list[dict[str, Any]]:
    result = await db.execute(
        select(MemoryDeclaration)
        .where(
            MemoryDeclaration.user_id == user_id,
            MemoryDeclaration.memory_id == memory_id,
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
    await db.execute(
        delete(MemoryDeclaration).where(
            MemoryDeclaration.user_id == user_id,
            MemoryDeclaration.memory_id == memory_id,
        )
    )
