"""Stage 7 experimental Graphiti Temporal / Episodic slice.

SQL MemoryDeclaration remains the only temporal truth. This module builds a
model-free, rebuildable Graphiti projection from reviewed declarations and
rehydrates every query result from SQL before returning product data.
"""
from __future__ import annotations

import hashlib
import os
import time
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.memory import MemoryDeclaration
from app.services.graphiti_shadow_service import graphiti_group_id
from app.utils.utc import to_utc_iso, utc_now_db


REVIEWED_TEMPORAL_STATUSES = ("confirmed", "superseded", "expired")


class GraphitiTemporalUnavailable(RuntimeError):
    """Safe capability-level failure for the optional temporal graph."""


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _safe_uuid_part(value: str) -> str:
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:24]


def _episode_uuid(*, user_id: int, declaration_id: int) -> str:
    return f"mnemox-memory-declaration-{int(user_id)}-{int(declaration_id)}"


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


def _records(result: Any) -> list[Any]:
    if result is None:
        return []
    records = getattr(result, "records", None)
    if records is not None:
        return list(records)
    if isinstance(result, tuple) and result:
        return list(result[0] or [])
    return list(result or [])


def _zero_graphiti_embedding() -> list[float]:
    try:
        from graphiti_core.embedder.client import EMBEDDING_DIM

        dimension = max(1, int(EMBEDDING_DIM))
    except Exception:
        dimension = 1024
    return [0.0] * dimension


def create_graphiti_temporal_graph() -> Any:
    """Create a Graphiti client that is structurally unable to call models.

    Stage 7 V1 uses reviewed SQL declarations and BM25 only. If Graphiti ever
    tries to invoke an LLM, embedding model or cross encoder, the call fails
    closed instead of silently consuming external quota.
    """
    os.environ["GRAPHITI_TELEMETRY_ENABLED"] = "false"
    if not str(settings.NEO4J_PASSWORD or ""):
        raise GraphitiTemporalUnavailable("graphiti_neo4j_credentials_missing")
    try:
        from graphiti_core import Graphiti
        from graphiti_core.cross_encoder.client import CrossEncoderClient
        from graphiti_core.driver.neo4j_driver import Neo4jDriver
        from graphiti_core.embedder.client import EmbedderClient
        from graphiti_core.llm_client.client import LLMClient
    except Exception as exc:  # pragma: no cover - optional dependency boundary
        raise GraphitiTemporalUnavailable("graphiti_optional_dependency_missing") from exc

    class _DisabledLlm(LLMClient):
        def __init__(self) -> None:
            super().__init__(config=None, cache=False)

        async def _generate_response(self, *_args: Any, **_kwargs: Any) -> Any:
            raise GraphitiTemporalUnavailable("graphiti_model_call_disabled")

    class _DisabledEmbedder(EmbedderClient):
        async def create(self, _input_data: Any) -> Any:
            raise GraphitiTemporalUnavailable("graphiti_embedding_call_disabled")

    class _DisabledCrossEncoder(CrossEncoderClient):
        async def rank(self, _query: str, _passages: list[str]) -> Any:
            raise GraphitiTemporalUnavailable("graphiti_reranker_call_disabled")

    driver = Neo4jDriver(
        uri=str(settings.NEO4J_URI),
        user=str(settings.NEO4J_USER),
        password=str(settings.NEO4J_PASSWORD),
        database=str(settings.NEO4J_DATABASE),
    )
    return Graphiti(
        graph_driver=driver,
        llm_client=_DisabledLlm(),
        embedder=_DisabledEmbedder(),
        cross_encoder=_DisabledCrossEncoder(),
        store_raw_episode_content=False,
    )


class GraphitiTemporalService:
    """Experimental temporal graph projection over SQL MemoryDeclaration."""

    backend = "graphiti"

    def __init__(self, db: AsyncSession, *, graph: Any | None = None) -> None:
        self.db = db
        if graph is None:
            graph = create_graphiti_temporal_graph()
            self._owns_graph = True
        else:
            self._owns_graph = False
        self.graph = graph
        self.driver = graph.driver

    async def close(self) -> None:
        if self._owns_graph:
            await self.graph.close()

    async def _reviewed_rows(self, *, user_id: int) -> list[MemoryDeclaration]:
        rows = await self.db.scalars(
            select(MemoryDeclaration)
            .where(
                MemoryDeclaration.user_id == int(user_id),
                MemoryDeclaration.review_status.in_(REVIEWED_TEMPORAL_STATUSES),
            )
            .order_by(
                MemoryDeclaration.valid_from.asc(),
                MemoryDeclaration.observed_at.asc(),
                MemoryDeclaration.id.asc(),
            )
        )
        return list(rows.all())

    async def _delete_group(self, *, user_id: int) -> None:
        await self.driver.execute_query(
            "MATCH (n) WHERE n.group_id = $group_id DETACH DELETE n",
            params={"group_id": graphiti_group_id(int(user_id))},
        )

    async def rebuild_user(self, *, user_id: int) -> dict[str, Any]:
        """Rebuild one user's deterministic temporal projection from SQL."""
        user_id = int(user_id)
        started = time.perf_counter()
        rows = await self._reviewed_rows(user_id=user_id)
        group_id = graphiti_group_id(user_id)
        try:
            from graphiti_core.edges import EntityEdge
            from graphiti_core.nodes import EntityNode
        except Exception as exc:  # pragma: no cover - optional dependency boundary
            raise GraphitiTemporalUnavailable("graphiti_optional_dependency_missing") from exc

        try:
            await self._delete_group(user_id=user_id)
            await self.graph.build_indices_and_constraints()
            nodes: dict[str, Any] = {}
            zero_embedding = _zero_graphiti_embedding()
            for declaration in rows:
                subject_key = str(declaration.subject or "user")
                fact_slot_key = str(declaration.fact_key or declaration.predicate or "fact")
                subject_uuid = (
                    f"mnemox-temporal-subject-{user_id}-{_safe_uuid_part(subject_key)}"
                )
                slot_uuid = (
                    f"mnemox-temporal-slot-{user_id}-{_safe_uuid_part(fact_slot_key)}"
                )
                if subject_uuid not in nodes:
                    nodes[subject_uuid] = EntityNode(
                        uuid=subject_uuid,
                        name=subject_key,
                        group_id=group_id,
                        created_at=_as_utc(declaration.created_at)
                        or _as_utc(declaration.valid_from)
                        or datetime.now(timezone.utc),
                        name_embedding=list(zero_embedding),
                        attributes={"mnemox_kind": "temporal_subject"},
                    )
                    await nodes[subject_uuid].save(self.driver)
                if slot_uuid not in nodes:
                    nodes[slot_uuid] = EntityNode(
                        uuid=slot_uuid,
                        name=str(declaration.predicate or fact_slot_key),
                        group_id=group_id,
                        created_at=_as_utc(declaration.created_at)
                        or _as_utc(declaration.valid_from)
                        or datetime.now(timezone.utc),
                        name_embedding=list(zero_embedding),
                        attributes={
                            "mnemox_kind": "temporal_fact_slot",
                            "fact_key": fact_slot_key,
                        },
                    )
                    await nodes[slot_uuid].save(self.driver)

                valid_from = _as_utc(declaration.valid_from) or datetime.now(timezone.utc)
                valid_to = _as_utc(declaration.valid_to)
                observed_at = _as_utc(declaration.observed_at) or valid_from
                edge = EntityEdge(
                    uuid=f"mnemox-temporal-edge-{user_id}-{int(declaration.id)}",
                    group_id=group_id,
                    source_node_uuid=subject_uuid,
                    target_node_uuid=slot_uuid,
                    created_at=observed_at,
                    name=str(declaration.predicate or fact_slot_key),
                    fact=(
                        f"{str(declaration.predicate or fact_slot_key)} = "
                        f"{str(declaration.value)}"
                    ),
                    fact_embedding=list(zero_embedding),
                    episodes=[
                        _episode_uuid(
                            user_id=user_id,
                            declaration_id=int(declaration.id),
                        )
                    ],
                    valid_at=valid_from,
                    invalid_at=valid_to,
                    expired_at=(
                        valid_to
                        if str(declaration.review_status) == "expired" and valid_to is not None
                        else None
                    ),
                    reference_time=observed_at,
                    attributes={
                        "mnemox_kind": "temporal_declaration",
                        "declaration_id": int(declaration.id),
                        "fact_key": fact_slot_key,
                        "review_status": str(declaration.review_status),
                    },
                )
                await edge.save(self.driver)
        except GraphitiTemporalUnavailable:
            raise
        except Exception as exc:
            raise GraphitiTemporalUnavailable("graphiti_temporal_rebuild_unavailable") from exc

        return {
            "backend": self.backend,
            "authoritative": False,
            "user_id": user_id,
            "rebuilt": True,
            "declarations": len(rows),
            "nodes": len(nodes),
            "latency_ms": round((time.perf_counter() - started) * 1000.0, 3),
            "external_model_calls": 0,
            "embedding_calls": 0,
            "configured_model_cost": 0.0,
            "telemetry_enabled": False,
            "raw_episode_storage": False,
        }

    async def _bm25_edges(
        self,
        *,
        user_id: int,
        query: str,
        limit: int,
    ) -> list[Any]:
        try:
            from graphiti_core.search.search_config import (
                EdgeReranker,
                EdgeSearchConfig,
                EdgeSearchMethod,
                SearchConfig,
            )
            search_config = SearchConfig(
                edge_config=EdgeSearchConfig(
                    search_methods=[EdgeSearchMethod.bm25],
                    reranker=EdgeReranker.rrf,
                ),
                limit=max(1, min(100, int(limit))),
            )
            result = await self.graph.search_(
                str(query),
                config=search_config,
                group_ids=[graphiti_group_id(int(user_id))],
            )
            return list(result.edges or [])
        except GraphitiTemporalUnavailable:
            raise
        except Exception as exc:
            raise GraphitiTemporalUnavailable("graphiti_temporal_query_unavailable") from exc

    async def query(
        self,
        *,
        user_id: int,
        query: str,
        as_of: datetime | None = None,
        fact_key: str | None = None,
        limit: int = 10,
    ) -> dict[str, Any]:
        user_id = int(user_id)
        clean_query = str(query or "").strip()
        if not clean_query:
            raise ValueError("query must not be empty")
        requested = max(1, min(25, int(limit)))
        point = _as_utc(as_of) or _as_utc(utc_now_db()) or datetime.now(timezone.utc)
        started = time.perf_counter()
        edges = await self._bm25_edges(
            user_id=user_id,
            query=clean_query,
            limit=max(requested, min(100, requested * 4)),
        )

        group_id = graphiti_group_id(user_id)
        declaration_ids: list[int] = []
        filtered_edges = 0
        unmapped_edges = 0
        for edge in edges:
            if str(getattr(edge, "group_id", "")) != group_id:
                filtered_edges += 1
                continue
            if not _edge_active_at(edge, as_of=point):
                filtered_edges += 1
                continue
            mapped = [
                declaration_id
                for episode in list(getattr(edge, "episodes", None) or [])
                if (
                    declaration_id := _declaration_id_from_episode(
                        user_id=user_id,
                        episode_uuid=episode,
                    )
                )
                is not None
            ]
            if not mapped:
                unmapped_edges += 1
                continue
            declaration_ids.extend(mapped)
            if len(set(declaration_ids)) >= requested:
                break

        unique_ids = tuple(dict.fromkeys(declaration_ids))[:requested]
        if not unique_ids:
            return {
                "status": "no_result",
                "as_of": point.isoformat(),
                "results": [],
                "runtime": {
                    "backend": self.backend,
                    "authoritative": False,
                    "latency_ms": round((time.perf_counter() - started) * 1000.0, 3),
                    "returned_edges": len(edges),
                    "filtered_edges": filtered_edges,
                    "unmapped_edges": unmapped_edges,
                    "external_model_calls": 0,
                    "embedding_calls": 0,
                },
            }

        conditions = [
            MemoryDeclaration.user_id == user_id,
            MemoryDeclaration.id.in_(unique_ids),
            MemoryDeclaration.review_status.in_(REVIEWED_TEMPORAL_STATUSES),
            MemoryDeclaration.valid_from <= point.replace(tzinfo=None),
            or_(
                MemoryDeclaration.valid_to.is_(None),
                MemoryDeclaration.valid_to > point.replace(tzinfo=None),
            ),
        ]
        clean_fact_key = str(fact_key or "").strip()
        if clean_fact_key:
            conditions.append(MemoryDeclaration.fact_key == clean_fact_key)
        rows = list(
            (
                await self.db.scalars(
                    select(MemoryDeclaration)
                    .where(*conditions)
                    .order_by(
                        MemoryDeclaration.valid_from.desc(),
                        MemoryDeclaration.observed_at.desc(),
                        MemoryDeclaration.id.desc(),
                    )
                )
            ).all()
        )
        by_id = {int(row.id): row for row in rows}
        ordered = [by_id[value] for value in unique_ids if value in by_id][:requested]
        payload = [
            {
                "declaration_id": int(row.id),
                "fact_key": str(row.fact_key),
                "subject": str(row.subject),
                "predicate": str(row.predicate),
                "value": str(row.value),
                "confidence": round(float(row.confidence), 4),
                "review_status": str(row.review_status),
                "valid_from": to_utc_iso(row.valid_from) if row.valid_from else None,
                "valid_to": to_utc_iso(row.valid_to) if row.valid_to else None,
                "observed_at": to_utc_iso(row.observed_at) if row.observed_at else None,
                "source_type": str(row.source_type),
            }
            for row in ordered
        ]
        return {
            "status": "ok" if payload else "no_result",
            "as_of": point.isoformat(),
            "results": payload,
            "runtime": {
                "backend": self.backend,
                "authoritative": False,
                "latency_ms": round((time.perf_counter() - started) * 1000.0, 3),
                "returned_edges": len(edges),
                "filtered_edges": filtered_edges,
                "unmapped_edges": unmapped_edges,
                "external_model_calls": 0,
                "embedding_calls": 0,
            },
        }

    async def delete_user_projection(self, *, user_id: int) -> dict[str, Any]:
        try:
            await self._delete_group(user_id=int(user_id))
        except Exception as exc:
            raise GraphitiTemporalUnavailable("graphiti_temporal_delete_unavailable") from exc
        return {
            "backend": self.backend,
            "authoritative": False,
            "deleted": True,
            "user_id": int(user_id),
        }

    async def status(self, *, user_id: int) -> dict[str, Any]:
        user_id = int(user_id)
        sql_count = int(
            await self.db.scalar(
                select(func.count(MemoryDeclaration.id)).where(
                    MemoryDeclaration.user_id == user_id,
                    MemoryDeclaration.review_status.in_(REVIEWED_TEMPORAL_STATUSES),
                )
            )
            or 0
        )
        try:
            health_check = getattr(self.driver, "health_check", None)
            if callable(health_check):
                await health_check()
            result = await self.driver.execute_query(
                "MATCH ()-[e:RELATES_TO]->() "
                "WHERE e.group_id = $group_id AND e.mnemox_kind = 'temporal_declaration' "
                "RETURN count(e) AS projected_edges",
                params={"group_id": graphiti_group_id(user_id)},
            )
            records = _records(result)
            projected_edges = int(records[0]["projected_edges"]) if records else 0
        except Exception as exc:
            return {
                "ok": False,
                "backend": self.backend,
                "authoritative": False,
                "mode": "experimental_explicit_rebuild",
                "reviewed_declarations": sql_count,
                "error_type": exc.__class__.__name__,
                "telemetry_enabled": False,
                "external_model_calls": 0,
            }
        return {
            "ok": True,
            "backend": self.backend,
            "authoritative": False,
            "mode": "experimental_explicit_rebuild",
            "reviewed_declarations": sql_count,
            "projected_edges": projected_edges,
            "caught_up": projected_edges == sql_count,
            "telemetry_enabled": False,
            "external_model_calls": 0,
            "embedding_calls": 0,
            "configured_model_cost": 0.0,
        }
