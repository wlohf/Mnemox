"""Canonical, auditable declarations for user-controlled memories."""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.memory import MemoryDeclaration, UserMemory


MANUAL_DECLARATION_VERSION = "manual-memory-declaration-v1"
ACTIVE_DECLARATION_STATUSES = ("confirmed", "staged")


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
