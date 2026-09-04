"""Sanitized Stage 6 graph shadow comparisons.

Shadow candidates never change product output. Diagnostics intentionally contain
only aggregate mismatch counts and latency, not queries, Claim text, or raw IDs.
"""
from __future__ import annotations

import asyncio
import time
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.memory import MemoryDeclaration
from app.services.graph_projection_status_service import neo4j_projection_lag_summary
from app.services.graph_store.base import GraphHit
from app.services.graph_store.neo4j_store import Neo4jGraphStore
from app.services.graphiti_shadow_service import GraphitiShadowAdapter
from app.utils.error_safety import safe_exception_summary
from app.utils.utc import to_db_utc


def _signature(hit: GraphHit) -> tuple[int, str, int]:
    return (int(hit.object_id), str(hit.path_type), int(hit.depth))


async def compare_neo4j_claim_shadow(
    db: AsyncSession,
    *,
    user_id: int,
    claim_ids: Sequence[int],
    patterns: Sequence[str],
    depth: int,
    limit: int,
    sql_hits: Sequence[GraphHit],
) -> dict[str, Any]:
    """Compare one fixed-path SQL result with Neo4j without exposing raw data."""
    started = time.perf_counter()
    store: Neo4jGraphStore | None = None
    try:
        store = Neo4jGraphStore(db)
        shadow_hits = await asyncio.wait_for(
            store.expand_claims(
                user_id=int(user_id),
                claim_ids=tuple(int(value) for value in claim_ids),
                patterns=tuple(str(value) for value in patterns),
                depth=int(depth),
                limit=int(limit),
            ),
            timeout=float(settings.NEO4J_GRAPH_SHADOW_TIMEOUT_SECONDS),
        )
    except Exception as exc:
        return {
            "backend": "neo4j",
            "status": "unavailable",
            "latency_ms": round((time.perf_counter() - started) * 1000.0, 3),
            "error": safe_exception_summary(exc),
        }
    finally:
        if store is not None:
            try:
                await store.close()
            except Exception:
                pass

    sql_signatures = {_signature(hit) for hit in sql_hits}
    shadow_signatures = {_signature(hit) for hit in shadow_hits}
    sql_ids = {value[0] for value in sql_signatures}
    shadow_ids = {value[0] for value in shadow_signatures}
    return {
        "backend": "neo4j",
        "status": "compared",
        "latency_ms": round((time.perf_counter() - started) * 1000.0, 3),
        "sql_count": len(sql_hits),
        "shadow_count": len(shadow_hits),
        "id_set_match": sql_ids == shadow_ids,
        "missing_count": len(sql_ids - shadow_ids),
        "extra_count": len(shadow_ids - sql_ids),
        "path_mismatch_count": len(sql_signatures.symmetric_difference(shadow_signatures)),
    }


async def compare_graphiti_temporal_shadow(
    db: AsyncSession,
    *,
    user_id: int,
    fact_key: str,
    query: str,
    as_of: datetime,
    limit: int = 10,
    adapter: GraphitiShadowAdapter | None = None,
) -> dict[str, Any]:
    """Compare Graphiti temporal retrieval with canonical SQL without exposing content.

    This evaluator is intentionally fact-key scoped.  SQL remains the source of
    truth for temporal validity; Graphiti is measured only on whether its search
    can recover the declaration(s) that SQL says are valid at ``as_of``.
    """
    user_id = int(user_id)
    point = to_db_utc(as_of)
    expected_ids = {
        int(value)
        for value in (
            await db.scalars(
                select(MemoryDeclaration.id).where(
                    MemoryDeclaration.user_id == user_id,
                    MemoryDeclaration.fact_key == str(fact_key),
                    MemoryDeclaration.review_status.in_(("confirmed", "superseded", "expired")),
                    MemoryDeclaration.valid_from <= point,
                    or_(
                        MemoryDeclaration.valid_to.is_(None),
                        MemoryDeclaration.valid_to > point,
                    ),
                )
            )
        ).all()
    }
    owns_adapter = adapter is None
    shadow = adapter or GraphitiShadowAdapter(db)
    started = time.perf_counter()
    try:
        result = await asyncio.wait_for(
            shadow.search_temporal(
                user_id=user_id,
                query=str(query),
                as_of=as_of,
                limit=max(1, min(50, int(limit))),
            ),
            timeout=float(settings.GRAPHITI_SHADOW_TIMEOUT_SECONDS),
        )
    except Exception as exc:
        return {
            "backend": "graphiti",
            "status": "unavailable",
            "latency_ms": round((time.perf_counter() - started) * 1000.0, 3),
            "error_type": exc.__class__.__name__,
            "sql_expected_count": len(expected_ids),
        }
    finally:
        if owns_adapter:
            try:
                await shadow.close()
            except Exception:
                pass

    shadow_ids = set(result.declaration_ids)
    return {
        "backend": "graphiti",
        "status": "compared",
        "latency_ms": result.latency_ms,
        "sql_expected_count": len(expected_ids),
        "shadow_mapped_count": len(shadow_ids),
        "expected_recall": (
            1.0 if not expected_ids else round(len(expected_ids & shadow_ids) / len(expected_ids), 6)
        ),
        "stale_or_wrong_count": len(shadow_ids - expected_ids),
        "missing_count": len(expected_ids - shadow_ids),
        "filtered_edge_count": int(result.filtered_edges),
        "unmapped_edge_count": int(result.unmapped_edges),
    }
