"""Stage 6 Graphiti shadow adapter.

Graphiti is an independent candidate from Neo4jGraphStore. It is never imported
or initialized unless explicitly requested. SQL remains authoritative and this
adapter only feeds confirmed, currently visible Claim/Evidence episodes.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.knowledge import (
    Claim,
    ClaimEvidence,
    KnowledgeSource,
    KnowledgeSourceRevision,
)
from app.models.memory import MemoryDeclaration
from app.utils.error_safety import safe_exception_summary
from app.utils.utc import to_utc_iso


class GraphitiDriver(Protocol):
    async def execute_query(self, cypher_query_: str, **kwargs: Any) -> Any: ...
    async def health_check(self) -> Any: ...


class GraphitiClient(Protocol):
    driver: GraphitiDriver

    async def build_indices_and_constraints(self, delete_existing: bool = False) -> Any: ...
    async def add_episode(self, **kwargs: Any) -> Any: ...
    async def search(
        self,
        query: str,
        *,
        group_ids: list[str] | None = None,
        num_results: int = 10,
        **kwargs: Any,
    ) -> list[Any]: ...
    async def close(self) -> Any: ...


@dataclass(frozen=True)
class GraphitiTemporalSearchResult:
    user_id: int
    declaration_ids: tuple[int, ...]
    returned_edges: int
    filtered_edges: int
    unmapped_edges: int
    latency_ms: float


def graphiti_group_id(user_id: int) -> str:
    # graphiti-core 0.30 validates group ids as [A-Za-z0-9_-]+.
    # Colons are rejected at search time even if lower-level writes accepted them.
    return f"mnemox_user_{int(user_id)}"


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _edge_active_at(edge: Any, *, as_of: datetime) -> bool:
    point = _as_utc(as_of)
    if point is None:
        return False
    valid_at = _as_utc(getattr(edge, "valid_at", None))
    invalid_at = _as_utc(getattr(edge, "invalid_at", None))
    expired_at = _as_utc(getattr(edge, "expired_at", None))
    if valid_at is not None and valid_at > point:
        return False
    if invalid_at is not None and invalid_at <= point:
        return False
    if expired_at is not None and expired_at <= point:
        return False
    return True


def _declaration_id_from_episode(*, user_id: int, episode_uuid: Any) -> int | None:
    prefix = f"mnemox-memory-declaration-{int(user_id)}-"
    value = str(episode_uuid or "")
    if not value.startswith(prefix):
        return None
    suffix = value[len(prefix) :]
    if not suffix.isdigit():
        return None
    declaration_id = int(suffix)
    return declaration_id if declaration_id > 0 else None


def create_graphiti_client() -> tuple[GraphitiClient, Any]:
    """Create the optional Graphiti client with telemetry disabled first."""
    os.environ["GRAPHITI_TELEMETRY_ENABLED"] = "false"
    if not str(settings.NEO4J_PASSWORD or ""):
        raise RuntimeError("neo4j_password_missing")
    try:
        from graphiti_core import Graphiti
        from graphiti_core.driver.neo4j_driver import Neo4jDriver
        from graphiti_core.nodes import EpisodeType
    except Exception as exc:  # pragma: no cover - optional spike dependency
        raise RuntimeError("graphiti_optional_dependency_missing") from exc

    driver = Neo4jDriver(
        uri=str(settings.NEO4J_URI),
        user=str(settings.NEO4J_USER),
        password=str(settings.NEO4J_PASSWORD),
        database=str(settings.NEO4J_DATABASE),
    )
    return Graphiti(graph_driver=driver, store_raw_episode_content=False), EpisodeType


class GraphitiShadowAdapter:
    """Read-only-from-SQL Graphiti ingestion boundary for Stage 6 evaluation."""

    backend = "graphiti"

    def __init__(
        self,
        db: AsyncSession,
        *,
        client: GraphitiClient | None = None,
        episode_type: Any | None = None,
    ) -> None:
        self.db = db
        if client is None:
            client, episode_type = create_graphiti_client()
            self._owns_client = True
        else:
            self._owns_client = False
        self.client = client
        self.episode_type = episode_type

    async def close(self) -> None:
        if self._owns_client:
            await self.client.close()

    async def _delete_group(self, *, group_id: str) -> None:
        # graphiti-core 0.30 removed the older high-level delete_group helper.
        # Its Neo4j graph remains group-scoped, so Shadow lifecycle deletes only
        # nodes with our deterministic user group_id. Parameters are never
        # interpolated into Cypher.
        await self.client.driver.execute_query(
            "MATCH (n) WHERE n.group_id = $group_id DETACH DELETE n",
            params={"group_id": str(group_id)},
        )

    async def _visible_claim_rows(self, *, user_id: int) -> list[tuple[Claim, KnowledgeSource]]:
        rows = await self.db.execute(
            select(Claim, KnowledgeSource)
            .join(KnowledgeSourceRevision, KnowledgeSourceRevision.id == Claim.source_revision_id)
            .join(KnowledgeSource, KnowledgeSource.id == KnowledgeSourceRevision.knowledge_source_id)
            .where(
                Claim.user_id == int(user_id),
                Claim.review_status == "confirmed",
                Claim.lifecycle_status == "active",
                KnowledgeSourceRevision.user_id == int(user_id),
                KnowledgeSourceRevision.status == "current",
                KnowledgeSource.user_id == int(user_id),
                KnowledgeSource.status == "active",
                exists().where(
                    ClaimEvidence.user_id == int(user_id),
                    ClaimEvidence.claim_id == Claim.id,
                ),
            )
            .order_by(Claim.id.asc())
        )
        return list(rows.all())

    async def _temporal_declaration_rows(self, *, user_id: int) -> list[MemoryDeclaration]:
        """Return only reviewed temporal history, never staged conflict candidates."""
        rows = await self.db.scalars(
            select(MemoryDeclaration)
            .where(
                MemoryDeclaration.user_id == int(user_id),
                MemoryDeclaration.review_status.in_(("confirmed", "superseded", "expired")),
            )
            .order_by(
                MemoryDeclaration.valid_from.asc(),
                MemoryDeclaration.observed_at.asc(),
                MemoryDeclaration.id.asc(),
            )
        )
        return list(rows.all())

    @staticmethod
    def _temporal_episode_body(row: MemoryDeclaration) -> str:
        valid_from = to_utc_iso(row.valid_from) if row.valid_from else "unknown"
        valid_to = to_utc_iso(row.valid_to) if row.valid_to else "current"
        return "\n".join(
            (
                f"Subject: {str(row.subject)}",
                f"Predicate: {str(row.predicate)}",
                f"Value: {str(row.value)}",
                f"Valid from: {valid_from}",
                f"Valid to: {valid_to}",
                f"Review status: {str(row.review_status)}",
            )
        )

    async def rebuild_user(self, *, user_id: int) -> dict[str, Any]:
        """Rebuild one user's Graphiti group from reviewed Claims and temporal state."""
        user_id = int(user_id)
        group_id = graphiti_group_id(user_id)
        await self._delete_group(group_id=group_id)
        await self.client.build_indices_and_constraints()
        claim_rows = await self._visible_claim_rows(user_id=user_id)
        for claim, source in claim_rows:
            reference_time = claim.reviewed_at or claim.updated_at or claim.created_at
            if reference_time is not None and reference_time.tzinfo is None:
                reference_time = reference_time.replace(tzinfo=timezone.utc)
            await self.client.add_episode(
                name=f"claim:{int(claim.id)}",
                episode_body=str(claim.statement),
                source_description=(
                    f"Mnemox confirmed Claim from {str(source.source_type)}; "
                    f"source_key={str(source.source_key)}"
                ),
                source=(getattr(self.episode_type, "text", None) if self.episode_type is not None else "text"),
                group_id=group_id,
                reference_time=reference_time,
                uuid=f"mnemox-claim-{user_id}-{int(claim.id)}",
                update_communities=False,
            )

        temporal_rows = await self._temporal_declaration_rows(user_id=user_id)
        for declaration in temporal_rows:
            reference_time = declaration.observed_at or declaration.valid_from
            if reference_time is not None and reference_time.tzinfo is None:
                reference_time = reference_time.replace(tzinfo=timezone.utc)
            await self.client.add_episode(
                name=f"memory_declaration:{int(declaration.id)}",
                episode_body=self._temporal_episode_body(declaration),
                source_description="Mnemox reviewed temporal memory declaration",
                source=(getattr(self.episode_type, "text", None) if self.episode_type is not None else "text"),
                group_id=group_id,
                reference_time=reference_time,
                uuid=f"mnemox-memory-declaration-{user_id}-{int(declaration.id)}",
                update_communities=False,
            )
        return {
            "backend": self.backend,
            "user_id": user_id,
            "rebuilt": True,
            "episodes": len(claim_rows) + len(temporal_rows),
            "claim_episodes": len(claim_rows),
            "temporal_episodes": len(temporal_rows),
            "telemetry_enabled": False,
            "raw_episode_storage": False,
        }

    async def delete_source(self, *, user_id: int, source_key: str) -> dict[str, Any]:
        # Graphiti's public lifecycle is group-oriented. In Shadow we favor
        # correctness over write efficiency: after canonical SQL tombstones a
        # source, rebuild the user's group so stale episode/fact state cannot
        # survive. Incremental source deletion can be benchmarked later.
        result = await self.rebuild_user(user_id=int(user_id))
        return {**result, "source_key": str(source_key), "delete_strategy": "rebuild_user"}

    async def search_temporal(
        self,
        *,
        user_id: int,
        query: str,
        as_of: datetime,
        limit: int = 10,
    ) -> GraphitiTemporalSearchResult:
        """Search one user's Graphiti facts and return only mapped temporal declaration ids.

        The raw Graphiti fact text never leaves this adapter.  Stage 6 shadow
        comparison only needs canonical SQL declaration ids plus aggregate
        counts, so user query/fact content is not copied into diagnostics.
        """
        user_id = int(user_id)
        requested = max(1, min(50, int(limit)))
        group_id = graphiti_group_id(user_id)
        started = time.perf_counter()
        edges = await self.client.search(
            str(query),
            group_ids=[group_id],
            num_results=max(requested, min(100, requested * 4)),
        )
        declaration_ids: list[int] = []
        filtered_edges = 0
        unmapped_edges = 0
        for edge in list(edges or []):
            if str(getattr(edge, "group_id", "")) != group_id:
                filtered_edges += 1
                continue
            if not _edge_active_at(edge, as_of=as_of):
                filtered_edges += 1
                continue
            mapped = {
                declaration_id
                for episode_uuid in list(getattr(edge, "episodes", None) or [])
                if (
                    declaration_id := _declaration_id_from_episode(
                        user_id=user_id,
                        episode_uuid=episode_uuid,
                    )
                )
                is not None
            }
            if not mapped:
                unmapped_edges += 1
                continue
            declaration_ids.extend(sorted(mapped))
            if len(set(declaration_ids)) >= requested:
                break
        unique_ids = tuple(dict.fromkeys(declaration_ids))[:requested]
        return GraphitiTemporalSearchResult(
            user_id=user_id,
            declaration_ids=unique_ids,
            returned_edges=len(list(edges or [])),
            filtered_edges=filtered_edges,
            unmapped_edges=unmapped_edges,
            latency_ms=round((time.perf_counter() - started) * 1000.0, 3),
        )

    async def health(self) -> dict[str, Any]:
        try:
            driver = getattr(self.client, "driver", None)
            health_check = getattr(driver, "health_check", None)
            if callable(health_check):
                await health_check()
        except Exception as exc:
            return {
                "ok": False,
                "backend": self.backend,
                "authoritative": False,
                "telemetry_enabled": False,
                "error": safe_exception_summary(exc),
            }
        return {
            "ok": True,
            "backend": self.backend,
            "authoritative": False,
            "telemetry_enabled": False,
        }
