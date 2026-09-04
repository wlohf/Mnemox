"""Storage-neutral read fallback for an optional graph execution backend."""
from __future__ import annotations

import time
from collections.abc import Awaitable, Callable, Sequence
from typing import Any, TypeVar

from app.services.graph_store.base import GraphHit, GraphPath, GraphStore, TraversalDirection


T = TypeVar("T")


class FallbackGraphStore:
    """Use a preferred GraphStore for reads and fall back to SQL-compatible reads.

    Projection lifecycle operations deliberately do not fall back: pretending a
    Neo4j rebuild/delete succeeded because canonical SQL is healthy would hide a
    stale projection. Each instance is request-scoped, so ``last_diagnostics``
    is safe to expose to that request without cross-request mutation.
    """

    def __init__(self, primary: GraphStore, fallback: GraphStore) -> None:
        self.primary = primary
        self.fallback = fallback
        self.backend = str(getattr(primary, "backend", "primary"))
        self.last_diagnostics: dict[str, Any] = {
            "backend": self.backend,
            "fallback_used": False,
        }

    async def _read_with_fallback(
        self,
        *,
        operation: str,
        primary_call: Callable[[], Awaitable[T]],
        fallback_call: Callable[[], Awaitable[T]],
    ) -> T:
        started = time.perf_counter()
        try:
            result = await primary_call()
        except Exception as exc:
            primary_latency_ms = round((time.perf_counter() - started) * 1000.0, 3)
            fallback_started = time.perf_counter()
            try:
                result = await fallback_call()
            except Exception:
                # Preserve the fallback exception: callers need to know when the
                # requested capability is unavailable on both backends.
                self.last_diagnostics = {
                    "backend": self.backend,
                    "operation": operation,
                    "fallback_used": True,
                    "fallback_succeeded": False,
                    "primary_error_type": exc.__class__.__name__,
                    "primary_latency_ms": primary_latency_ms,
                    "fallback_latency_ms": round(
                        (time.perf_counter() - fallback_started) * 1000.0,
                        3,
                    ),
                }
                raise
            self.last_diagnostics = {
                "backend": self.backend,
                "operation": operation,
                "fallback_used": True,
                "fallback_succeeded": True,
                "primary_error_type": exc.__class__.__name__,
                "primary_latency_ms": primary_latency_ms,
                "fallback_latency_ms": round(
                    (time.perf_counter() - fallback_started) * 1000.0,
                    3,
                ),
            }
            return result

        self.last_diagnostics = {
            "backend": self.backend,
            "operation": operation,
            "fallback_used": False,
            "primary_latency_ms": round((time.perf_counter() - started) * 1000.0, 3),
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
        return await self._read_with_fallback(
            operation="expand_claims",
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
        return await self._read_with_fallback(
            operation="expand_concepts",
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

    async def source_claims(self, *, user_id: int, source_id: int, limit: int = 50) -> list[GraphHit]:
        return await self._read_with_fallback(
            operation="source_claims",
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
        return await self._read_with_fallback(
            operation="find_concept_paths",
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
        primary_health = await self.primary.health()
        fallback_health = await self.fallback.health()
        primary_ok = bool(primary_health.get("ok"))
        fallback_ok = bool(fallback_health.get("ok"))
        return {
            # ``ok`` answers whether the selected primary backend is healthy.
            # ``serving_ok`` separately answers whether read traffic can still
            # be served through the configured fallback.
            "ok": primary_ok,
            "serving_ok": primary_ok or fallback_ok,
            "fallback_available": fallback_ok,
            "backend": self.backend,
            "primary": primary_health,
            "fallback": fallback_health,
        }
