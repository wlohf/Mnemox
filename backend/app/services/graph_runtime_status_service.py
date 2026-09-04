"""Runtime readiness diagnostics for the optional graph execution backend.

Readiness is stricter than connectivity: when Neo4j is selected, the primary
backend is ready only if it is healthy *and* the current user's rebuildable
projection has no outstanding or failed work. Product serving readiness is
reported separately because SQL fallback may still serve safe reads.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.services.graph_shadow_service import neo4j_projection_lag_summary
from app.services.graph_store.factory import create_graph_store


async def graph_runtime_status(db: AsyncSession, *, user_id: int) -> dict[str, Any]:
    selected_backend = str(settings.GRAPH_BACKEND or "sql").strip().lower()

    try:
        store = create_graph_store(db)
        health = await store.health()
    except Exception as exc:
        return {
            "selected_backend": selected_backend,
            "projection_required": selected_backend == "neo4j",
            "primary_ready": False,
            "serving_ready": False,
            "health": {
                "ok": False,
                "backend": selected_backend,
                "error_type": exc.__class__.__name__,
            },
            "projection": None,
        }

    primary_healthy = bool(health.get("ok"))
    serving_healthy = bool(health.get("serving_ok", primary_healthy))

    if selected_backend != "neo4j":
        return {
            "selected_backend": selected_backend,
            "projection_required": False,
            "primary_ready": primary_healthy,
            "serving_ready": serving_healthy,
            "health": health,
            "projection": None,
        }

    projection = await neo4j_projection_lag_summary(db, user_id=int(user_id))
    counts = projection.get("status_counts") or {}
    pending = int(counts.get("pending", 0) or 0)
    processing = int(counts.get("processing", 0) or 0)
    failed = int(counts.get("failed", 0) or 0)
    dead_letter = int(projection.get("dead_letter_count", 0) or 0)
    projection_caught_up = pending == 0 and processing == 0 and failed == 0 and dead_letter == 0

    return {
        "selected_backend": selected_backend,
        "projection_required": True,
        "primary_ready": primary_healthy and projection_caught_up,
        "serving_ready": serving_healthy,
        "health": health,
        "projection": {
            **projection,
            "caught_up": projection_caught_up,
            "blocking_counts": {
                "pending": pending,
                "processing": processing,
                "failed": failed,
                "dead_letter": dead_letter,
            },
        },
    }
