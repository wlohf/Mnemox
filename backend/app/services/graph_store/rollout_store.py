"""Read-path rollout gate for the optional Neo4j GraphStore.

The gate solves a failure mode that ordinary exception fallback cannot detect:
a Neo4j service can be reachable while its rebuildable projection is stale. A
user is allowed onto the Neo4j read path only when both conditions hold:

1. the user belongs to the configured rollout cohort; and
2. that user's Neo4j projection has no pending/processing/failed/DLQ work.

If either condition is false, reads go directly to canonical SQL. Once admitted,
ordinary Neo4j query failures are still handled by ``FallbackGraphStore``.
Projection lifecycle operations are never hidden by this rollout gate.
"""
from __future__ import annotations

import hashlib
from collections.abc import Awaitable, Callable, Sequence
from typing import Any, TypeVar

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.services.graph_projection_status_service import neo4j_projection_lag_summary
from app.services.graph_store.base import GraphHit, GraphPath, GraphStore, TraversalDirection


T = TypeVar("T")


def parse_rollout_user_ids(raw: str | None) -> frozenset[int]:
    values: set[int] = set()
    for token in str(raw or "").split(","):
        token = token.strip()
        if not token:
            continue
        try:
            value = int(token)
        except ValueError:
            continue
        if value > 0:
            values.add(value)
    return frozenset(values)


def neo4j_rollout_bucket(user_id: int) -> int:
    """Return a stable 0-99 bucket without relying on Python's salted hash()."""
    digest = hashlib.sha256(f"mnemox-neo4j-rollout:{int(user_id)}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") % 100


def neo4j_rollout_decision(
    *,
    user_id: int,
    percent: int | None = None,
    forced_user_ids: frozenset[int] | None = None,
) -> dict[str, Any]:
    percent_value = max(
        0,
        min(
            100,
            int(
                settings.NEO4J_GRAPH_ROLLOUT_PERCENT
                if percent is None
                else percent
            ),
        ),
    )
    forced = (
        parse_rollout_user_ids(settings.NEO4J_GRAPH_ROLLOUT_USER_IDS)
        if forced_user_ids is None
        else forced_user_ids
    )
    user_id = int(user_id)
    bucket = neo4j_rollout_bucket(user_id)
    forced_selected = user_id in forced
    selected = forced_selected or percent_value >= 100 or (
        percent_value > 0 and bucket < percent_value
    )
    return {
        "selected": selected,
        "forced": forced_selected,
        "percent": percent_value,
        "bucket": bucket,
    }


def neo4j_projection_caught_up(summary: dict[str, Any]) -> tuple[bool, dict[str, int]]:
    counts = summary.get("status_counts") or {}
    blocking = {
        "pending": int(counts.get("pending", 0) or 0),
        "processing": int(counts.get("processing", 0) or 0),
        "failed": int(counts.get("failed", 0) or 0),
        "dead_letter": int(summary.get("dead_letter_count", 0) or 0),
        "uninitialized": 0 if bool(summary.get("initialized")) else 1,
    }
    return not any(blocking.values()), blocking


class Neo4jRolloutGraphStore:
    """Route eligible, caught-up users to Neo4j and everyone else to SQL."""

    backend = "neo4j"

    def __init__(
        self,
        *,
        db: AsyncSession,
        primary: GraphStore,
        fallback: GraphStore,
        projection_summary: Callable[..., Awaitable[dict[str, Any]]] = neo4j_projection_lag_summary,
    ) -> None:
        self.db = db
        self.primary = primary
        self.fallback = fallback
        self._projection_summary = projection_summary
        self.last_diagnostics: dict[str, Any] = {
            "backend": self.backend,
            "effective_backend": "sql",
            "route_reason": "not_evaluated",
        }

    async def _route_read(
        self,
        *,
        operation: str,
        user_id: int,
        primary_call: Callable[[], Awaitable[T]],
        fallback_call: Callable[[], Awaitable[T]],
    ) -> T:
        rollout = neo4j_rollout_decision(user_id=int(user_id))
        base_diagnostics: dict[str, Any] = {
            "backend": self.backend,
            "operation": operation,
            "rollout_selected": bool(rollout["selected"]),
            "rollout_forced": bool(rollout["forced"]),
            "rollout_percent": int(rollout["percent"]),
            "rollout_bucket": int(rollout["bucket"]),
        }

        if not rollout["selected"]:
            self.last_diagnostics = {
                **base_diagnostics,
                "effective_backend": "sql",
                "route_reason": "rollout_not_selected",
            }
            return await fallback_call()

        try:
            projection = await self._projection_summary(self.db, user_id=int(user_id))
        except Exception as exc:
            self.last_diagnostics = {
                **base_diagnostics,
                "effective_backend": "sql",
                "route_reason": "projection_status_unavailable",
                "projection_error_type": exc.__class__.__name__,
            }
            return await fallback_call()

        projection_ready, blocking = neo4j_projection_caught_up(projection)
        if not projection_ready:
            self.last_diagnostics = {
                **base_diagnostics,
                "effective_backend": "sql",
                "route_reason": "projection_not_ready",
                "projection_blocking_counts": blocking,
            }
            return await fallback_call()

        try:
            result = await primary_call()
        except Exception:
            nested = dict(getattr(self.primary, "last_diagnostics", {}) or {})
            self.last_diagnostics = {
                **base_diagnostics,
                "effective_backend": "sql" if nested.get("fallback_used") else "neo4j",
                "route_reason": "primary_error",
                "projection_ready": True,
                "primary": nested,
            }
            raise

        nested = dict(getattr(self.primary, "last_diagnostics", {}) or {})
        fallback_used = bool(nested.get("fallback_used"))
        self.last_diagnostics = {
            **base_diagnostics,
            "effective_backend": "sql" if fallback_used else "neo4j",
            "route_reason": "primary_fallback" if fallback_used else "neo4j_selected",
            "projection_ready": True,
            "primary": nested,
        }
        return result

    async def expand_claims(
        self,
        *,
        user_id: int,
        claim_ids: Sequence[int],
        patterns: Sequence[str],
        depth: int = 1,
        limit: int = 50,
    ) -> list[GraphHit]:
        return await self._route_read(
            operation="expand_claims",
            user_id=user_id,
            primary_call=lambda: self.primary.expand_claims(
                user_id=user_id,
                claim_ids=claim_ids,
                patterns=patterns,
                depth=depth,
                limit=limit,
            ),
            fallback_call=lambda: self.fallback.expand_claims(
                user_id=user_id,
                claim_ids=claim_ids,
                patterns=patterns,
                depth=depth,
                limit=limit,
            ),
        )

    async def expand_concepts(
        self,
        *,
        user_id: int,
        concept_ids: Sequence[int],
        patterns: Sequence[str],
        depth: int = 1,
        limit: int = 50,
    ) -> list[GraphHit]:
        return await self._route_read(
            operation="expand_concepts",
            user_id=user_id,
            primary_call=lambda: self.primary.expand_concepts(
                user_id=user_id,
                concept_ids=concept_ids,
                patterns=patterns,
                depth=depth,
                limit=limit,
            ),
            fallback_call=lambda: self.fallback.expand_concepts(
                user_id=user_id,
                concept_ids=concept_ids,
                patterns=patterns,
                depth=depth,
                limit=limit,
            ),
        )

    async def source_claims(
        self,
        *,
        user_id: int,
        source_id: int,
        limit: int = 50,
    ) -> list[GraphHit]:
        return await self._route_read(
            operation="source_claims",
            user_id=user_id,
            primary_call=lambda: self.primary.source_claims(
                user_id=user_id,
                source_id=source_id,
                limit=limit,
            ),
            fallback_call=lambda: self.fallback.source_claims(
                user_id=user_id,
                source_id=source_id,
                limit=limit,
            ),
        )

    async def find_concept_paths(
        self,
        *,
        user_id: int,
        start_concept_ids: Sequence[int],
        target_concept_ids: Sequence[int],
        relation_types: Sequence[str],
        direction: TraversalDirection = "outgoing",
        max_depth: int = 4,
        limit: int = 10,
    ) -> list[GraphPath]:
        return await self._route_read(
            operation="find_concept_paths",
            user_id=user_id,
            primary_call=lambda: self.primary.find_concept_paths(
                user_id=user_id,
                start_concept_ids=start_concept_ids,
                target_concept_ids=target_concept_ids,
                relation_types=relation_types,
                direction=direction,
                max_depth=max_depth,
                limit=limit,
            ),
            fallback_call=lambda: self.fallback.find_concept_paths(
                user_id=user_id,
                start_concept_ids=start_concept_ids,
                target_concept_ids=target_concept_ids,
                relation_types=relation_types,
                direction=direction,
                max_depth=max_depth,
                limit=limit,
            ),
        )

    async def rebuild_user(self, *, user_id: int) -> dict[str, Any]:
        return await self.primary.rebuild_user(user_id=user_id)

    async def delete_source(self, *, user_id: int, source_key: str) -> dict[str, Any]:
        return await self.primary.delete_source(user_id=user_id, source_key=source_key)

    async def health(self) -> dict[str, Any]:
        health = await self.primary.health()
        return {
            **health,
            "rollout_percent": int(settings.NEO4J_GRAPH_ROLLOUT_PERCENT),
            "rollout_forced_user_count": len(
                parse_rollout_user_ids(settings.NEO4J_GRAPH_ROLLOUT_USER_IDS)
            ),
        }
