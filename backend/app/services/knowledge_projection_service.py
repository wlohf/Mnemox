"""Knowledge-specific outbox and rebuildable embedding projection lifecycle."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from sqlalchemy import exists, func, or_, select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.config import settings
from app.models.concept import Concept, ConceptAlias
from app.models.knowledge import (
    Claim,
    KnowledgeEmbeddingProjection,
    KnowledgeProjectionOutbox,
    KnowledgeSource,
    KnowledgeSourceRevision,
    KnowledgeUnit,
)
from app.services.knowledge_embedding_service import (
    KnowledgeEmbeddingUnavailable,
    get_knowledge_embedding_index,
    knowledge_embedding_configuration,
)
from app.services.sparse_knowledge_index import (
    create_sparse_knowledge_index,
    mark_sparse_knowledge_dirty,
)
from app.utils.error_safety import safe_exception_summary
from app.utils.operation_lock import serialized_user_operation
from app.utils.utc import to_utc_iso, utc_now_db


OBJECT_TYPES = frozenset({"claim", "concept", "note_unit", "material_unit"})
KNOWLEDGE_PROJECTION_TARGET = "chroma_knowledge"
SPARSE_KNOWLEDGE_PROJECTION_TARGET = "sparse_knowledge"
NEO4J_GRAPH_PROJECTION_TARGET = "neo4j_graph"


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class KnowledgeObjectSnapshot:
    user_id: int
    object_type: str
    object_id: int
    text: str
    content_hash: str
    metadata: dict[str, str | int | float | bool]

    @property
    def vector_key(self) -> str:
        return f"u:{self.user_id}:knowledge:{self.object_type}:{self.object_id}"


async def load_knowledge_object(
    db: AsyncSession,
    *,
    user_id: int,
    object_type: str,
    object_id: int,
) -> KnowledgeObjectSnapshot | None:
    normalized_type = str(object_type).strip().lower()
    if normalized_type not in OBJECT_TYPES:
        raise ValueError("不支持的知识投影对象类型。")
    if normalized_type == "concept":
        concept = await db.scalar(
            select(Concept).where(
                Concept.id == int(object_id),
                Concept.user_id == int(user_id),
                Concept.review_status != "rejected",
            )
        )
        if concept is None:
            return None
        aliases = list(
            (
                await db.scalars(
                    select(ConceptAlias.alias)
                    .where(
                        ConceptAlias.user_id == int(user_id),
                        ConceptAlias.concept_id == int(concept.id),
                    )
                    .order_by(ConceptAlias.id)
                )
            ).all()
        )
        text = "\n".join(
            (
                f"名称：{concept.name}",
                f"别名：{', '.join(str(value) for value in aliases)}",
                f"定义：{str(concept.description or '')}",
            )
        )
        metadata = {
            "user_id": str(int(user_id)),
            "object_type": "concept",
            "object_id": int(concept.id),
            "review_status": str(concept.review_status),
        }
    elif normalized_type == "claim":
        claim = await db.scalar(
            select(Claim)
            .join(
                KnowledgeSourceRevision,
                KnowledgeSourceRevision.id == Claim.source_revision_id,
            )
            .join(
                KnowledgeSource,
                KnowledgeSource.id == KnowledgeSourceRevision.knowledge_source_id,
            )
            .where(
                Claim.id == int(object_id),
                Claim.user_id == int(user_id),
                Claim.lifecycle_status == "active",
                Claim.review_status != "rejected",
                KnowledgeSourceRevision.user_id == int(user_id),
                KnowledgeSourceRevision.status == "current",
                KnowledgeSource.user_id == int(user_id),
                KnowledgeSource.status == "active",
            )
        )
        if claim is None:
            return None
        text = str(claim.statement or "")
        metadata = {
            "user_id": str(int(user_id)),
            "object_type": "claim",
            "object_id": int(claim.id),
            "review_status": str(claim.review_status),
            "source_revision_id": int(claim.source_revision_id),
        }
    else:
        expected_source_type = "note" if normalized_type == "note_unit" else "material"
        unit = await db.scalar(
            select(KnowledgeUnit)
            .join(
                KnowledgeSourceRevision,
                KnowledgeSourceRevision.id == KnowledgeUnit.source_revision_id,
            )
            .join(
                KnowledgeSource,
                KnowledgeSource.id == KnowledgeSourceRevision.knowledge_source_id,
            )
            .where(
                KnowledgeUnit.id == int(object_id),
                KnowledgeUnit.user_id == int(user_id),
                KnowledgeSourceRevision.user_id == int(user_id),
                KnowledgeSourceRevision.status == "current",
                KnowledgeSource.user_id == int(user_id),
                KnowledgeSource.source_type == expected_source_type,
                KnowledgeSource.status == "active",
            )
        )
        if unit is None:
            return None
        text = str(unit.text or "")
        metadata = {
            "user_id": str(int(user_id)),
            "object_type": normalized_type,
            "object_id": int(unit.id),
            "source_revision_id": int(unit.source_revision_id),
            "unit_type": str(unit.unit_type),
        }
    if not text.strip():
        return None
    return KnowledgeObjectSnapshot(
        user_id=int(user_id),
        object_type=normalized_type,
        object_id=int(object_id),
        text=text,
        content_hash=_sha256(text),
        metadata=metadata,
    )


async def enqueue_knowledge_projection(
    db: AsyncSession,
    *,
    user_id: int,
    aggregate_type: str,
    aggregate_id: int,
    operation: str,
    idempotency_key: str,
    aggregate_version: int = 1,
    payload: dict[str, Any] | None = None,
    requeue_existing: bool = False,
    projection_target: str = KNOWLEDGE_PROJECTION_TARGET,
) -> KnowledgeProjectionOutbox:
    values = {
        "user_id": int(user_id),
        "aggregate_type": str(aggregate_type),
        "aggregate_id": int(aggregate_id),
        "aggregate_version": max(1, int(aggregate_version)),
        "operation": str(operation),
        "projection_target": str(projection_target),
        "idempotency_key": str(idempotency_key)[:200],
        "payload_version": 1,
        "payload": dict(payload or {}),
        "status": "pending",
        "attempts": 0,
        "available_at": utc_now_db(),
    }
    bind = db.get_bind()
    dialect = bind.dialect.name if bind is not None else ""
    if dialect == "postgresql":
        await db.execute(
            postgresql_insert(KnowledgeProjectionOutbox)
            .values(**values)
            .on_conflict_do_nothing(constraint="uq_knowledge_projection_outbox_user_key")
        )
    elif dialect == "sqlite":
        await db.execute(
            sqlite_insert(KnowledgeProjectionOutbox)
            .values(**values)
            .on_conflict_do_nothing(index_elements=["user_id", "idempotency_key"])
        )
    else:
        existing = await db.scalar(
            select(KnowledgeProjectionOutbox).where(
                KnowledgeProjectionOutbox.user_id == int(user_id),
                KnowledgeProjectionOutbox.idempotency_key == str(idempotency_key)[:200],
            )
        )
        if existing is None:
            db.add(KnowledgeProjectionOutbox(**values))
            await db.flush()
    row = await db.scalar(
        select(KnowledgeProjectionOutbox).where(
            KnowledgeProjectionOutbox.user_id == int(user_id),
            KnowledgeProjectionOutbox.idempotency_key == str(idempotency_key)[:200],
        )
    )
    if row is None:
        raise RuntimeError("知识投影 Outbox 写入后无法读取。")
    if requeue_existing and row.status != "processing":
        row.status = "pending"
        row.attempts = 0
        row.available_at = utc_now_db()
        row.locked_at = None
        row.lease_owner = None
        row.processed_at = None
        row.last_error = None
        row.dead_lettered_at = None
        await db.flush()
    return row


def _sparse_projection_enabled() -> bool:
    return str(settings.KNOWLEDGE_SPARSE_BACKEND or "reference").strip().casefold() != "reference"


def _neo4j_projection_enabled() -> bool:
    return bool(
        str(settings.GRAPH_BACKEND or "sql").strip().casefold() == "neo4j"
        or settings.NEO4J_GRAPH_SHADOW
        or settings.NEO4J_GRAPH_ENABLED
    )


async def enqueue_neo4j_user_rebuild(
    db: AsyncSession,
    *,
    user_id: int,
    force: bool = False,
) -> KnowledgeProjectionOutbox | None:
    """Queue a rebuild-only graph projection without dropping in-flight dirtiness.

    The normal slot is reused to keep the queue bounded. If that slot is already
    processing and a mutation forces another rebuild, a fixed follow-up slot is
    queued instead. The Neo4j worker serializes rebuilds per user, so repeated
    mutations collapse into at most one pending follow-up rather than spawning an
    unbounded number of full rebuild tasks.
    """
    if not _neo4j_projection_enabled():
        return None
    user_id = int(user_id)
    primary = await enqueue_knowledge_projection(
        db,
        user_id=user_id,
        aggregate_type="user",
        aggregate_id=user_id,
        operation="rebuild_user",
        idempotency_key=f"neo4j:user:{user_id}:rebuild:v1",
        payload={},
        requeue_existing=bool(force),
        projection_target=NEO4J_GRAPH_PROJECTION_TARGET,
    )
    if bool(force) and str(primary.status) == "processing":
        return await enqueue_knowledge_projection(
            db,
            user_id=user_id,
            aggregate_type="user",
            aggregate_id=user_id,
            operation="rebuild_user",
            idempotency_key=f"neo4j:user:{user_id}:rebuild:followup:v1",
            payload={"coalesced_followup": True},
            requeue_existing=True,
            projection_target=NEO4J_GRAPH_PROJECTION_TARGET,
        )
    return primary


async def _enqueue_sparse_claim_projection(
    db: AsyncSession,
    *,
    user_id: int,
    claim_id: int,
    operation: str,
) -> KnowledgeProjectionOutbox | None:
    if not _sparse_projection_enabled():
        return None
    claim = await db.scalar(
        select(Claim).where(
            Claim.id == int(claim_id),
            Claim.user_id == int(user_id),
        )
    )
    version = "missing"
    if claim is not None:
        version = _sha256(
            "|".join(
                (
                    str(claim.statement or ""),
                    str(claim.review_status or ""),
                    str(claim.lifecycle_status or ""),
                    str(claim.source_revision_id or ""),
                    str(claim.updated_at or ""),
                    str(claim.reviewed_at or ""),
                )
            )
        )[:16]
    return await enqueue_knowledge_projection(
        db,
        user_id=int(user_id),
        aggregate_type="claim",
        aggregate_id=int(claim_id),
        operation=str(operation),
        idempotency_key=f"sparse:claim:{int(claim_id)}:{operation}:{version}",
        payload={"object_type": "claim"},
        projection_target=SPARSE_KNOWLEDGE_PROJECTION_TARGET,
    )


async def enqueue_knowledge_object_projection(
    db: AsyncSession,
    *,
    user_id: int,
    object_type: str,
    object_id: int,
    force: bool = False,
    mark_graph_dirty: bool = True,
) -> KnowledgeProjectionOutbox:
    if mark_graph_dirty:
        # Neo4j remains rebuild-only in this phase. Any graph-affecting object
        # mutation requeues the single per-user rebuild command so a processed
        # historical row cannot make a later projection appear caught up.
        await enqueue_neo4j_user_rebuild(
            db,
            user_id=int(user_id),
            force=True,
        )
    if str(object_type) == "claim":
        await mark_sparse_knowledge_dirty(
            db,
            user_id=int(user_id),
            claim_id=int(object_id),
        )
    snapshot = await load_knowledge_object(
        db,
        user_id=int(user_id),
        object_type=str(object_type),
        object_id=int(object_id),
    )
    config = knowledge_embedding_configuration()
    aggregate_type = "unit" if str(object_type).endswith("_unit") else str(object_type)
    if snapshot is None:
        return await enqueue_knowledge_projection_delete(
            db,
            user_id=int(user_id),
            object_type=str(object_type),
            object_id=int(object_id),
            mark_graph_dirty=False,
        )
    key = (
        f"chroma:{snapshot.object_type}:{snapshot.object_id}:"
        f"upsert:{snapshot.content_hash}:{config.fingerprint}"
    )
    row = await enqueue_knowledge_projection(
        db,
        user_id=int(user_id),
        aggregate_type=aggregate_type,
        aggregate_id=int(object_id),
        operation="upsert",
        idempotency_key=key,
        payload={"object_type": snapshot.object_type},
        requeue_existing=bool(force),
    )
    if str(object_type) == "claim":
        await _enqueue_sparse_claim_projection(
            db,
            user_id=int(user_id),
            claim_id=int(object_id),
            operation="upsert",
        )
    return row


async def enqueue_knowledge_projection_delete(
    db: AsyncSession,
    *,
    user_id: int,
    object_type: str,
    object_id: int,
    mark_graph_dirty: bool = True,
) -> KnowledgeProjectionOutbox:
    if mark_graph_dirty:
        await enqueue_neo4j_user_rebuild(
            db,
            user_id=int(user_id),
            force=True,
        )
    if str(object_type) == "claim":
        await mark_sparse_knowledge_dirty(
            db,
            user_id=int(user_id),
            claim_id=int(object_id),
        )
    aggregate_type = "unit" if str(object_type).endswith("_unit") else str(object_type)
    row = await enqueue_knowledge_projection(
        db,
        user_id=int(user_id),
        aggregate_type=aggregate_type,
        aggregate_id=int(object_id),
        operation="delete",
        idempotency_key=f"chroma:{object_type}:{int(object_id)}:delete",
        payload={"object_type": str(object_type)},
        requeue_existing=True,
    )
    if str(object_type) == "claim":
        await _enqueue_sparse_claim_projection(
            db,
            user_id=int(user_id),
            claim_id=int(object_id),
            operation="delete",
        )
    return row


async def enqueue_user_knowledge_rebuild(
    db: AsyncSession,
    *,
    user_id: int,
    force: bool = False,
) -> KnowledgeProjectionOutbox:
    await mark_sparse_knowledge_dirty(db, user_id=int(user_id))
    await enqueue_neo4j_user_rebuild(
        db,
        user_id=int(user_id),
        force=bool(force),
    )
    if _sparse_projection_enabled():
        await enqueue_knowledge_projection(
            db,
            user_id=int(user_id),
            aggregate_type="user",
            aggregate_id=int(user_id),
            operation="rebuild_user",
            idempotency_key=f"sparse:user:{int(user_id)}:rebuild",
            payload={},
            requeue_existing=bool(force),
            projection_target=SPARSE_KNOWLEDGE_PROJECTION_TARGET,
        )
    config = knowledge_embedding_configuration()
    key = f"chroma:user:{int(user_id)}:rebuild:{config.fingerprint}"
    existing = await db.scalar(
        select(KnowledgeProjectionOutbox).where(
            KnowledgeProjectionOutbox.user_id == int(user_id),
            KnowledgeProjectionOutbox.idempotency_key == key,
        )
    )
    if existing is not None and force:
        existing.status = "pending"
        existing.attempts = 0
        existing.available_at = utc_now_db()
        existing.locked_at = None
        existing.lease_owner = None
        existing.processed_at = None
        existing.last_error = None
        existing.dead_lettered_at = None
        await db.flush()
        return existing
    return await enqueue_knowledge_projection(
        db,
        user_id=int(user_id),
        aggregate_type="user",
        aggregate_id=int(user_id),
        operation="rebuild_user",
        idempotency_key=key,
        payload={},
    )


async def schedule_user_knowledge_rebuild(
    db: AsyncSession,
    *,
    user_id: int,
) -> dict[str, int]:
    config = knowledge_embedding_configuration()
    stale = list(
        (
            await db.scalars(
                select(KnowledgeEmbeddingProjection).where(
                    KnowledgeEmbeddingProjection.user_id == int(user_id),
                    KnowledgeEmbeddingProjection.status.not_in(("deleted", "deleting")),
                    KnowledgeEmbeddingProjection.configuration_fingerprint
                    != config.fingerprint,
                )
            )
        ).all()
    )
    for row in stale:
        row.status = "degraded"
        row.last_error = "knowledge_embedding_configuration_changed"

    concept_ids = list(
        (
            await db.scalars(
                select(Concept.id).where(
                    Concept.user_id == int(user_id),
                    Concept.review_status != "rejected",
                )
            )
        ).all()
    )
    claim_ids = list(
        (
            await db.scalars(
                select(Claim.id)
                .join(
                    KnowledgeSourceRevision,
                    KnowledgeSourceRevision.id == Claim.source_revision_id,
                )
                .join(
                    KnowledgeSource,
                    KnowledgeSource.id == KnowledgeSourceRevision.knowledge_source_id,
                )
                .where(
                    Claim.user_id == int(user_id),
                    Claim.lifecycle_status == "active",
                    Claim.review_status != "rejected",
                    KnowledgeSourceRevision.status == "current",
                    KnowledgeSource.status == "active",
                )
            )
        ).all()
    )
    unit_rows = (
        await db.execute(
            select(KnowledgeUnit.id, KnowledgeSource.source_type)
            .join(
                KnowledgeSourceRevision,
                KnowledgeSourceRevision.id == KnowledgeUnit.source_revision_id,
            )
            .join(
                KnowledgeSource,
                KnowledgeSource.id == KnowledgeSourceRevision.knowledge_source_id,
            )
            .where(
                KnowledgeUnit.user_id == int(user_id),
                KnowledgeSourceRevision.status == "current",
                KnowledgeSource.status == "active",
            )
        )
    ).all()
    active_keys = {
        *(('concept', int(value)) for value in concept_ids),
        *(('claim', int(value)) for value in claim_ids),
        *(
            (
                "note_unit" if str(source_type) == "note" else "material_unit",
                int(unit_id),
            )
            for unit_id, source_type in unit_rows
        ),
    }
    for object_type, object_id in sorted(active_keys):
        await enqueue_knowledge_object_projection(
            db,
            user_id=int(user_id),
            object_type=object_type,
            object_id=object_id,
            force=True,
            mark_graph_dirty=False,
        )
    projection_rows = list(
        (
            await db.scalars(
                select(KnowledgeEmbeddingProjection).where(
                    KnowledgeEmbeddingProjection.user_id == int(user_id),
                    KnowledgeEmbeddingProjection.status != "deleted",
                )
            )
        ).all()
    )
    stale_objects = {
        (str(row.object_type), int(row.object_id))
        for row in projection_rows
        if (str(row.object_type), int(row.object_id)) not in active_keys
    }
    for object_type, object_id in sorted(stale_objects):
        await enqueue_knowledge_projection_delete(
            db,
            user_id=int(user_id),
            object_type=object_type,
            object_id=object_id,
            mark_graph_dirty=False,
        )
    await db.flush()
    return {
        "enqueued": len(active_keys) + len(stale_objects),
        "active_objects": len(active_keys),
        "stale_objects": len(stale_objects),
        "degraded": len(stale),
    }


async def invalidate_knowledge_embedding_configuration(
    db: AsyncSession,
) -> dict[str, int]:
    """Mark old metadata stale and enqueue one durable rebuild per affected user."""

    config = knowledge_embedding_configuration()
    projection_rows = list(
        (
            await db.scalars(
                select(KnowledgeEmbeddingProjection).where(
                    KnowledgeEmbeddingProjection.status.not_in(("deleted", "deleting")),
                    KnowledgeEmbeddingProjection.configuration_fingerprint
                    != config.fingerprint,
                )
            )
        ).all()
    )
    for row in projection_rows:
        row.status = "degraded"
        row.last_error = "knowledge_embedding_configuration_changed"
    user_ids = {
        *(int(value) for value in await db.scalars(select(Concept.user_id).distinct())),
        *(
            int(value)
            for value in await db.scalars(select(KnowledgeSource.user_id).distinct())
        ),
        *(int(row.user_id) for row in projection_rows),
    }
    for user_id in sorted(user_ids):
        await enqueue_user_knowledge_rebuild(db, user_id=user_id, force=True)
    await db.flush()
    return {
        "users": len(user_ids),
        "stale_projections": len(projection_rows),
        "rebuilds_enqueued": len(user_ids),
    }


async def _ensure_projection_row(
    db: AsyncSession,
    *,
    snapshot: KnowledgeObjectSnapshot,
    embedding_index: Any,
) -> KnowledgeEmbeddingProjection:
    config = knowledge_embedding_configuration()
    stale_rows = list(
        (
            await db.scalars(
                select(KnowledgeEmbeddingProjection).where(
                    KnowledgeEmbeddingProjection.user_id == int(snapshot.user_id),
                    KnowledgeEmbeddingProjection.object_type == snapshot.object_type,
                    KnowledgeEmbeddingProjection.object_id == int(snapshot.object_id),
                    KnowledgeEmbeddingProjection.status != "deleted",
                    KnowledgeEmbeddingProjection.configuration_fingerprint
                    != config.fingerprint,
                )
            )
        ).all()
    )
    for stale in stale_rows:
        stale.status = "deleting"
        await db.flush()
        await embedding_index.delete(
            vector_key=str(stale.vector_key),
            collection=str(stale.collection),
        )
        stale.status = "deleted"
        stale.deleted_at = utc_now_db()
        stale.last_error = None
    row = await db.scalar(
        select(KnowledgeEmbeddingProjection).where(
            KnowledgeEmbeddingProjection.user_id == int(snapshot.user_id),
            KnowledgeEmbeddingProjection.object_type == snapshot.object_type,
            KnowledgeEmbeddingProjection.object_id == int(snapshot.object_id),
            KnowledgeEmbeddingProjection.embedding_model == config.embedding_model,
        )
    )
    if row is None:
        row = KnowledgeEmbeddingProjection(
            user_id=int(snapshot.user_id),
            object_type=snapshot.object_type,
            object_id=int(snapshot.object_id),
            content_hash=snapshot.content_hash,
            configuration_fingerprint=config.fingerprint,
            embedding_model=config.embedding_model,
            collection=config.collection,
            vector_key=snapshot.vector_key,
            status="pending",
        )
        db.add(row)
        await db.flush()
    else:
        if (
            row.status != "deleted"
            and (
                row.configuration_fingerprint != config.fingerprint
                or row.collection != config.collection
            )
        ):
            row.status = "deleting"
            await db.flush()
            await embedding_index.delete(
                vector_key=str(row.vector_key),
                collection=str(row.collection),
            )
        row.content_hash = snapshot.content_hash
        row.configuration_fingerprint = config.fingerprint
        row.collection = config.collection
        row.vector_key = snapshot.vector_key
        row.status = "pending"
        row.deleted_at = None
        await db.flush()
    return row


async def _delete_object_projections(
    db: AsyncSession,
    *,
    user_id: int,
    object_type: str,
    object_id: int,
    embedding_index: Any,
) -> int:
    rows = list(
        (
            await db.scalars(
                select(KnowledgeEmbeddingProjection).where(
                    KnowledgeEmbeddingProjection.user_id == int(user_id),
                    KnowledgeEmbeddingProjection.object_type == str(object_type),
                    KnowledgeEmbeddingProjection.object_id == int(object_id),
                    KnowledgeEmbeddingProjection.status != "deleted",
                )
            )
        ).all()
    )
    for row in rows:
        row.status = "deleting"
        await db.flush()
        await embedding_index.delete(vector_key=row.vector_key, collection=row.collection)
        row.status = "deleted"
        row.deleted_at = utc_now_db()
        row.last_error = None
    await db.flush()
    return len(rows)


async def claim_next_knowledge_projection(
    db: AsyncSession,
    *,
    worker_id: str,
    max_attempts: int,
    lease_seconds: int,
    projection_targets: tuple[str, ...] = (KNOWLEDGE_PROJECTION_TARGET,),
) -> KnowledgeProjectionOutbox | None:
    now = utc_now_db()
    cutoff = now - timedelta(seconds=max(1, int(lease_seconds)))
    eligible = or_(
        (
            KnowledgeProjectionOutbox.status.in_(("pending", "failed"))
            & (KnowledgeProjectionOutbox.available_at <= now)
            & (KnowledgeProjectionOutbox.dead_lettered_at.is_(None))
        ),
        (
            (KnowledgeProjectionOutbox.status == "processing")
            & (KnowledgeProjectionOutbox.locked_at.is_not(None))
            & (KnowledgeProjectionOutbox.locked_at <= cutoff)
        ),
    )
    other_graph_task = aliased(KnowledgeProjectionOutbox)
    neo4j_user_serialized = or_(
        KnowledgeProjectionOutbox.projection_target != NEO4J_GRAPH_PROJECTION_TARGET,
        ~exists().where(
            other_graph_task.user_id == KnowledgeProjectionOutbox.user_id,
            other_graph_task.projection_target == NEO4J_GRAPH_PROJECTION_TARGET,
            other_graph_task.status == "processing",
            other_graph_task.id != KnowledgeProjectionOutbox.id,
        ),
    )
    row = await db.scalar(
        select(KnowledgeProjectionOutbox)
        .where(
            eligible,
            KnowledgeProjectionOutbox.attempts < max(1, int(max_attempts)),
            KnowledgeProjectionOutbox.projection_target.in_(tuple(projection_targets)),
            neo4j_user_serialized,
        )
        .order_by(
            KnowledgeProjectionOutbox.available_at,
            KnowledgeProjectionOutbox.created_at,
            KnowledgeProjectionOutbox.id,
        )
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    if row is None:
        return None
    row.status = "processing"
    row.attempts = int(row.attempts or 0) + 1
    row.locked_at = now
    row.lease_owner = str(worker_id)[:120]
    row.last_error = None
    await db.flush()
    return row


async def process_claimed_knowledge_projection(
    db: AsyncSession,
    *,
    outbox_id: int,
    worker_id: str,
    embedding_index: Any | None = None,
    max_attempts: int,
    retry_base_seconds: float,
) -> str:
    row = await db.scalar(
        select(KnowledgeProjectionOutbox)
        .where(
            KnowledgeProjectionOutbox.id == int(outbox_id),
            KnowledgeProjectionOutbox.status == "processing",
            KnowledgeProjectionOutbox.lease_owner == str(worker_id)[:120],
        )
        .with_for_update()
    )
    if row is None:
        raise LookupError("知识投影任务不存在或租约已失效。")
    try:
        if str(row.projection_target) == NEO4J_GRAPH_PROJECTION_TARGET:
            if row.operation != "rebuild_user":
                raise ValueError("Neo4j Shadow 投影当前只接受 rebuild_user。")
            from app.services.graph_store.neo4j_store import Neo4jGraphStore

            async with serialized_user_operation(
                db,
                namespace="neo4j-graph-rebuild",
                user_id=int(row.user_id),
            ):
                graph_store = Neo4jGraphStore(db)
                try:
                    await graph_store.rebuild_user(user_id=int(row.user_id))
                finally:
                    await graph_store.close()
        elif str(row.projection_target) == SPARSE_KNOWLEDGE_PROJECTION_TARGET:
            sparse_index = create_sparse_knowledge_index(db)
            if row.operation == "rebuild_user":
                await sparse_index.rebuild_user(user_id=int(row.user_id))
            else:
                object_type = str((row.payload or {}).get("object_type") or "")
                if object_type != "claim":
                    raise ValueError("Sparse 知识投影当前只支持 Claim。")
                if row.operation == "delete":
                    await sparse_index.delete_claim(
                        user_id=int(row.user_id),
                        claim_id=int(row.aggregate_id),
                        clear_dirty=True,
                    )
                else:
                    await sparse_index.upsert_claim(
                        user_id=int(row.user_id),
                        claim_id=int(row.aggregate_id),
                        clear_dirty=True,
                    )
        else:
            index = embedding_index or get_knowledge_embedding_index()
            if row.operation == "rebuild_user":
                await schedule_user_knowledge_rebuild(db, user_id=int(row.user_id))
            else:
                object_type = str((row.payload or {}).get("object_type") or "")
                if object_type not in OBJECT_TYPES:
                    raise ValueError("知识投影任务缺少有效 object_type。")
                if row.operation == "delete":
                    await _delete_object_projections(
                        db,
                        user_id=int(row.user_id),
                        object_type=object_type,
                        object_id=int(row.aggregate_id),
                        embedding_index=index,
                    )
                else:
                    snapshot = await load_knowledge_object(
                        db,
                        user_id=int(row.user_id),
                        object_type=object_type,
                        object_id=int(row.aggregate_id),
                    )
                    if snapshot is None:
                        await _delete_object_projections(
                            db,
                            user_id=int(row.user_id),
                            object_type=object_type,
                            object_id=int(row.aggregate_id),
                            embedding_index=index,
                        )
                    else:
                        projection = await _ensure_projection_row(
                            db,
                            snapshot=snapshot,
                            embedding_index=index,
                        )
                        projection.attempt_count = int(projection.attempt_count or 0) + 1
                        try:
                            await index.upsert(
                                vector_key=snapshot.vector_key,
                                text=snapshot.text,
                                metadata=snapshot.metadata,
                            )
                        except KnowledgeEmbeddingUnavailable as exc:
                            projection.status = "degraded"
                            projection.last_error = safe_exception_summary(exc)[:500]
                        else:
                            projection.status = "ready"
                            projection.indexed_at = utc_now_db()
                            projection.last_error = None
        row.status = "processed"
        row.processed_at = utc_now_db()
        row.locked_at = None
        row.lease_owner = None
        row.last_error = None
    except Exception as exc:
        now = utc_now_db()
        row.status = "failed"
        row.locked_at = None
        row.lease_owner = None
        row.last_error = safe_exception_summary(exc)[:500]
        row.available_at = now + timedelta(
            seconds=max(0.0, float(retry_base_seconds))
            * (2 ** max(0, int(row.attempts or 1) - 1))
        )
        if int(row.attempts or 0) >= max(1, int(max_attempts)):
            row.dead_lettered_at = now
        if str(row.projection_target) == KNOWLEDGE_PROJECTION_TARGET:
            projection = await db.scalar(
                select(KnowledgeEmbeddingProjection).where(
                    KnowledgeEmbeddingProjection.user_id == int(row.user_id),
                    KnowledgeEmbeddingProjection.object_type
                    == str((row.payload or {}).get("object_type") or ""),
                    KnowledgeEmbeddingProjection.object_id == int(row.aggregate_id),
                    KnowledgeEmbeddingProjection.status.in_(("pending", "deleting")),
                )
            )
            if projection is not None:
                projection.status = "failed"
                projection.last_error = row.last_error
    await db.flush()
    return str(row.status)


async def knowledge_status_summary(db: AsyncSession, *, user_id: int) -> dict[str, Any]:
    projection_counts = dict(
        (
            await db.execute(
                select(
                    KnowledgeEmbeddingProjection.status,
                    func.count(KnowledgeEmbeddingProjection.id),
                )
                .where(KnowledgeEmbeddingProjection.user_id == int(user_id))
                .group_by(KnowledgeEmbeddingProjection.status)
            )
        ).all()
    )
    outbox_counts = dict(
        (
            await db.execute(
                select(
                    KnowledgeProjectionOutbox.status,
                    func.count(KnowledgeProjectionOutbox.id),
                )
                .where(KnowledgeProjectionOutbox.user_id == int(user_id))
                .group_by(KnowledgeProjectionOutbox.status)
            )
        ).all()
    )
    dead_letter = int(
        await db.scalar(
            select(func.count(KnowledgeProjectionOutbox.id)).where(
                KnowledgeProjectionOutbox.user_id == int(user_id),
                KnowledgeProjectionOutbox.dead_lettered_at.is_not(None),
            )
        )
        or 0
    )
    config = knowledge_embedding_configuration()
    last_success = await db.scalar(
        select(func.max(KnowledgeEmbeddingProjection.indexed_at)).where(
            KnowledgeEmbeddingProjection.user_id == int(user_id),
            KnowledgeEmbeddingProjection.status == "ready",
        )
    )
    return {
        "embedding_enabled": bool(config.enabled),
        "embedding_model": config.embedding_model,
        "collection": config.collection,
        "embedding_ready": int(projection_counts.get("ready", 0)),
        "embedding_degraded": int(projection_counts.get("degraded", 0)),
        "embedding_failed": int(projection_counts.get("failed", 0)),
        "projection_pending": int(outbox_counts.get("pending", 0)),
        "projection_processing": int(outbox_counts.get("processing", 0)),
        "projection_failed": int(outbox_counts.get("failed", 0)),
        "projection_dead_letter": dead_letter,
        "last_success_at": to_utc_iso(last_success) if last_success else None,
    }
