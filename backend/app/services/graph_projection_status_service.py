"""Projection readiness diagnostics for the optional Neo4j read model.

This module deliberately has no dependency on GraphStore implementations. It is
shared by runtime rollout, authenticated status, and Stage 6 Shadow diagnostics
without creating a graph-store import cycle.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.concept import Concept
from app.models.knowledge import KnowledgeProjectionOutbox, KnowledgeSource
from app.utils.utc import utc_now_db


async def neo4j_projection_lag_summary(
    db: AsyncSession,
    *,
    user_id: int,
) -> dict[str, Any]:
    """Return bounded per-user Neo4j backlog, initialization, and lag diagnostics."""
    rows = list(
        (
            await db.scalars(
                select(KnowledgeProjectionOutbox).where(
                    KnowledgeProjectionOutbox.user_id == int(user_id),
                    KnowledgeProjectionOutbox.projection_target == "neo4j_graph",
                )
            )
        ).all()
    )
    canonical_source_count = int(
        await db.scalar(
            select(func.count(KnowledgeSource.id)).where(
                KnowledgeSource.user_id == int(user_id),
                KnowledgeSource.status == "active",
            )
        )
        or 0
    )
    canonical_concept_count = int(
        await db.scalar(
            select(func.count(Concept.id)).where(
                Concept.user_id == int(user_id),
                Concept.review_status == "confirmed",
            )
        )
        or 0
    )
    canonical_graph_objects_present = (canonical_source_count + canonical_concept_count) > 0

    now = utc_now_db()
    counts: dict[str, int] = {}
    pending_ages: list[float] = []
    processed_lags: list[float] = []
    for row in rows:
        status = str(row.status or "unknown")
        counts[status] = counts.get(status, 0) + 1
        if status in {"pending", "failed", "processing"} and row.dead_lettered_at is None:
            pending_ages.append(max(0.0, (now - row.created_at).total_seconds()))
        if row.processed_at is not None:
            processed_lags.append(max(0.0, (row.processed_at - row.created_at).total_seconds()))

    successful_rebuild = any(
        str(row.operation) == "rebuild_user"
        and str(row.status) == "processed"
        and row.processed_at is not None
        and row.dead_lettered_at is None
        for row in rows
    )
    initialized = (not canonical_graph_objects_present) or successful_rebuild
    return {
        "backend": "neo4j",
        "tasks_total": len(rows),
        "status_counts": counts,
        "oldest_pending_age_seconds": round(max(pending_ages), 3) if pending_ages else 0.0,
        "latest_processed_lag_seconds": round(processed_lags[-1], 3) if processed_lags else 0.0,
        "dead_letter_count": sum(1 for row in rows if row.dead_lettered_at is not None),
        "canonical_source_count": canonical_source_count,
        "canonical_concept_count": canonical_concept_count,
        "canonical_graph_objects_present": canonical_graph_objects_present,
        "successful_rebuild": successful_rebuild,
        "initialized": initialized,
    }
