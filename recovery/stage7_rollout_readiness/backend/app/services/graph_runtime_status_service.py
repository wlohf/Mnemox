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
from app.services.graph_projection_status_service import neo4j_projection_lag_summary
from app.services.graph_store.factory import create_graph_store
from app.services.graph_store.rollout_store import (
    neo4j_projection_caught_up,
    neo4j_rollout_decision,
)


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

    rollout = neo4j_rollout_decision(user_id=int(user_id))
    try:
        projection = await neo4j_projection_lag_summary(db, user_id=int(user_id))
    except Exception as exc:
        return {
            "selected_backend": selected_backend,
            "effective_backend": "sql" if serving_healthy else "unavailable",
            "projection_required": True,
            "primary_ready": False,
            "serving_ready": serving_healthy,
            "rollout": rollout,
            "health": health,
            "projection": {
                "caught_up": False,
                "error_type": exc.__class__.__name__,
            },
        }

    projection_caught_up, blocking = neo4j_projection_caught_up(projection)
    primary_ready = primary_healthy and projection_caught_up
    neo4j_read_enabled = bool(rollout["selected"]) and primary_ready

    return {
        "selected_backend": selected_backend,
        "effective_backend": "neo4j" if neo4j_read_enabled else ("sql" if serving_healthy else "unavailable"),
        "projection_required": True,
        "primary_ready": primary_ready,
        "serving_ready": serving_healthy,
        "neo4j_read_enabled": neo4j_read_enabled,
        "rollout": rollout,
        "health": health,
        "projection": {
            **projection,
            "caught_up": projection_caught_up,
            "blocking_counts": blocking,
        },
    }
