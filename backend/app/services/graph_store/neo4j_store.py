"""Rebuildable Neo4j projection and optional GraphStore execution backend.

SQL remains authoritative. Stage 6 uses this adapter for Shadow validation;
Stage 7 may select it explicitly as an optional runtime backend. This module is
safe to import even when the optional ``neo4j`` package is not installed; the
driver is loaded only when a Neo4j operation is actually requested.
"""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from typing import Any, Protocol

from sqlalchemy import exists, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.concept import Concept, ConceptEdge, ConceptSourceEvidence
from app.models.knowledge import (
    Claim,
    ClaimConceptLink,
    ClaimEvidence,
    ClaimRelation,
    KnowledgeSource,
    KnowledgeSourceRevision,
    KnowledgeUnit,
)
from app.services.graph_store.base import (
    CLAIM_PATTERNS,
    CONCEPT_PATTERNS,
    GraphEdgeRef,
    GraphHit,
    GraphNodeRef,
    GraphPath,
    TraversalDirection,
)
from app.services.graph_store.sql_store import SqlGraphStore
from app.utils.error_safety import safe_exception_summary


CLAIM_CONCEPT_RELATION_TYPES = {
    "about": "ABOUT",
    "uses": "USES",
    "applies_to": "APPLIES_TO",
    "exemplifies": "EXEMPLIFIES",
}
CLAIM_RELATION_TYPES = {
    "supports": "SUPPORTS",
    "contradicts": "CONTRADICTS",
    "refines": "REFINES",
    "exemplifies": "EXEMPLIFIES",
    "analogous_to": "ANALOGOUS_TO",
}
CONCEPT_RELATION_TYPES = {
    "prerequisite_of": "PREREQUISITE_OF",
    "related_to": "RELATED_TO",
}
_DIRECT_CLAIM_RELATION_CYPHER = "SUPPORTS|CONTRADICTS|REFINES|EXEMPLIFIES|ANALOGOUS_TO"
_CONCEPT_RELATION_CYPHER = "PREREQUISITE_OF|RELATED_TO"


def _ids(values: Sequence[int]) -> tuple[int, ...]:
    return tuple(dict.fromkeys(int(value) for value in values if int(value) > 0))


def _bounds(depth: int, limit: int) -> tuple[int, int]:
    return max(1, min(3, int(depth))), max(1, min(100, int(limit)))


def _validate(patterns: Sequence[str], allowed: frozenset[str]) -> tuple[str, ...]:
    selected = tuple(dict.fromkeys(str(value) for value in patterns))
    unknown = set(selected) - allowed
    if unknown:
        raise ValueError(f"unsupported graph pattern: {', '.join(sorted(unknown))}")
    return selected


def _key(user_id: int, kind: str, sql_id: int) -> str:
    return f"u:{int(user_id)}:{str(kind)}:{int(sql_id)}"


class Neo4jExecutor(Protocol):
    async def execute(self, query: str, parameters: dict[str, Any] | None = None) -> list[dict[str, Any]]: ...
    async def verify_connectivity(self) -> None: ...
    async def close(self) -> None: ...


class Neo4jAsyncExecutor:
    """Thin adapter around the optional official Neo4j async driver."""

    def __init__(
        self,
        *,
        uri: str,
        user: str,
        password: str,
        database: str = "neo4j",
    ) -> None:
        try:
            from neo4j import AsyncGraphDatabase
        except Exception as exc:  # pragma: no cover - exercised without spike deps
            raise RuntimeError("neo4j_optional_dependency_missing") from exc
        self._driver = AsyncGraphDatabase.driver(str(uri), auth=(str(user), str(password)))
        self._database = str(database or "neo4j")

    async def execute(
        self,
        query: str,
        parameters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        result = await self._driver.execute_query(
            str(query),
            parameters_=dict(parameters or {}),
            database_=self._database,
        )
        return [record.data() for record in result.records]

    async def verify_connectivity(self) -> None:
        # execute_query supports an explicit database without relying on the
        # preview keyword accepted by verify_connectivity().
        await self._driver.execute_query("RETURN 1 AS ok", database_=self._database)

    async def close(self) -> None:
        await self._driver.close()


def create_neo4j_executor() -> Neo4jExecutor:
    if not str(settings.NEO4J_PASSWORD or ""):
        raise RuntimeError("neo4j_password_missing")
    return Neo4jAsyncExecutor(
        uri=str(settings.NEO4J_URI),
        user=str(settings.NEO4J_USER),
        password=str(settings.NEO4J_PASSWORD),
        database=str(settings.NEO4J_DATABASE),
    )


_shared_executor: Neo4jExecutor | None = None


def get_shared_neo4j_executor() -> Neo4jExecutor:
    """Return the process-wide Neo4j driver used by the optional runtime backend."""
    global _shared_executor
    if _shared_executor is None:
        _shared_executor = create_neo4j_executor()
    return _shared_executor


async def close_shared_neo4j_executor() -> None:
    """Close and forget the optional runtime driver during application shutdown."""
    global _shared_executor
    executor = _shared_executor
    _shared_executor = None
    if executor is not None:
        await executor.close()


class Neo4jGraphStore:
    """GraphStore backed by a disposable, SQL-rebuildable Neo4j projection."""

    backend = "neo4j"

    def __init__(self, db: AsyncSession, *, executor: Neo4jExecutor | None = None) -> None:
        self.db = db
        self.executor = executor or create_neo4j_executor()
        self._owns_executor = executor is None
        self._sql_fallback = SqlGraphStore(db)

    async def close(self) -> None:
        if self._owns_executor:
            await self.executor.close()

    async def ensure_schema(self) -> None:
        statements = (
            "CREATE CONSTRAINT mnemox_source_key IF NOT EXISTS FOR (n:Source) REQUIRE n.key IS UNIQUE",
            "CREATE CONSTRAINT mnemox_unit_key IF NOT EXISTS FOR (n:Unit) REQUIRE n.key IS UNIQUE",
            "CREATE CONSTRAINT mnemox_claim_key IF NOT EXISTS FOR (n:Claim) REQUIRE n.key IS UNIQUE",
            "CREATE CONSTRAINT mnemox_concept_key IF NOT EXISTS FOR (n:Concept) REQUIRE n.key IS UNIQUE",
            "CREATE INDEX mnemox_source_user_sql IF NOT EXISTS FOR (n:Source) ON (n.user_id, n.sql_id)",
            "CREATE INDEX mnemox_claim_user_sql IF NOT EXISTS FOR (n:Claim) ON (n.user_id, n.sql_id)",
            "CREATE INDEX mnemox_concept_user_sql IF NOT EXISTS FOR (n:Concept) ON (n.user_id, n.sql_id)",
        )
        for query in statements:
            await self.executor.execute(query)

    async def _visible_claim_ids(self, user_id: int) -> set[int]:
        rows = await self.db.scalars(
            select(Claim.id)
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
        )
        return {int(value) for value in rows.all()}

    async def rebuild_user(self, *, user_id: int) -> dict[str, Any]:
        user_id = int(user_id)
        await self.ensure_schema()
        await self.executor.execute(
            "MATCH (n {user_id: $user_id}) DETACH DELETE n",
            {"user_id": user_id},
        )

        source_rows = (await self.db.execute(
            select(KnowledgeSource, KnowledgeSourceRevision)
            .join(
                KnowledgeSourceRevision,
                KnowledgeSourceRevision.knowledge_source_id == KnowledgeSource.id,
            )
            .where(
                KnowledgeSource.user_id == user_id,
                KnowledgeSource.status == "active",
                KnowledgeSourceRevision.user_id == user_id,
                KnowledgeSourceRevision.status == "current",
            )
            .order_by(KnowledgeSource.id.asc())
        )).all()
        sources = [
            {
                "key": _key(user_id, "source", int(source.id)),
                "user_id": user_id,
                "sql_id": int(source.id),
                "source_key": str(source.source_key),
                "source_type": str(source.source_type),
                "revision_id": int(revision.id),
            }
            for source, revision in source_rows
        ]
        revision_to_source = {
            int(revision.id): int(source.id) for source, revision in source_rows
        }
        if sources:
            await self.executor.execute(
                "UNWIND $rows AS row MERGE (n:Source {key: row.key}) "
                "SET n.user_id=row.user_id, n.sql_id=row.sql_id, n.source_key=row.source_key, "
                "n.source_type=row.source_type, n.revision_id=row.revision_id",
                {"rows": sources},
            )

        unit_rows = list((await self.db.scalars(
            select(KnowledgeUnit)
            .where(
                KnowledgeUnit.user_id == user_id,
                KnowledgeUnit.source_revision_id.in_(tuple(revision_to_source) or (-1,)),
            )
            .order_by(KnowledgeUnit.id.asc())
        )).all())
        units = [
            {
                "key": _key(user_id, "unit", int(unit.id)),
                "user_id": user_id,
                "sql_id": int(unit.id),
                "unit_type": str(unit.unit_type),
                "source_key": _key(user_id, "source", revision_to_source[int(unit.source_revision_id)]),
            }
            for unit in unit_rows
        ]
        if units:
            await self.executor.execute(
                "UNWIND $rows AS row MERGE (u:Unit {key: row.key}) "
                "SET u.user_id=row.user_id, u.sql_id=row.sql_id, u.unit_type=row.unit_type "
                "WITH row,u MATCH (s:Source {key: row.source_key}) MERGE (s)-[:CONTAINS]->(u)",
                {"rows": units},
            )

        visible_claim_ids = await self._visible_claim_ids(user_id)
        claim_rows = list((await self.db.scalars(
            select(Claim)
            .where(Claim.user_id == user_id, Claim.id.in_(tuple(visible_claim_ids) or (-1,)))
            .order_by(Claim.id.asc())
        )).all())
        claims = [
            {
                "key": _key(user_id, "claim", int(claim.id)),
                "user_id": user_id,
                "sql_id": int(claim.id),
                "fingerprint": str(claim.fingerprint),
                "confidence": float(claim.confidence),
                "review_status": str(claim.review_status),
            }
            for claim in claim_rows
        ]
        if claims:
            await self.executor.execute(
                "UNWIND $rows AS row MERGE (c:Claim {key: row.key}) "
                "SET c.user_id=row.user_id, c.sql_id=row.sql_id, c.fingerprint=row.fingerprint, "
                "c.confidence=row.confidence, c.review_status=row.review_status",
                {"rows": claims},
            )

        evidence_rows = (await self.db.execute(
            select(ClaimEvidence.claim_id, ClaimEvidence.knowledge_unit_id)
            .where(
                ClaimEvidence.user_id == user_id,
                ClaimEvidence.claim_id.in_(tuple(visible_claim_ids) or (-1,)),
            )
            .order_by(ClaimEvidence.id.asc())
        )).all()
        evidence_links = [
            {
                "unit_key": _key(user_id, "unit", int(unit_id)),
                "claim_key": _key(user_id, "claim", int(claim_id)),
            }
            for claim_id, unit_id in evidence_rows
        ]
        if evidence_links:
            await self.executor.execute(
                "UNWIND $rows AS row MATCH (u:Unit {key: row.unit_key}), (c:Claim {key: row.claim_key}) "
                "MERGE (u)-[:STATES]->(c)",
                {"rows": evidence_links},
            )

        concept_rows = list((await self.db.scalars(
            select(Concept)
            .where(Concept.user_id == user_id, Concept.review_status == "confirmed")
            .order_by(Concept.id.asc())
        )).all())
        concept_ids = {int(row.id) for row in concept_rows}
        concepts = [
            {
                "key": _key(user_id, "concept", int(concept.id)),
                "user_id": user_id,
                "sql_id": int(concept.id),
                "name_normalized": str(concept.name_normalized or concept.name).casefold(),
                "review_status": str(concept.review_status),
            }
            for concept in concept_rows
        ]
        if concepts:
            await self.executor.execute(
                "UNWIND $rows AS row MERGE (c:Concept {key: row.key}) "
                "SET c.user_id=row.user_id, c.sql_id=row.sql_id, "
                "c.name_normalized=row.name_normalized, c.review_status=row.review_status",
                {"rows": concepts},
            )

        claim_links = list((await self.db.scalars(
            select(ClaimConceptLink)
            .where(
                ClaimConceptLink.user_id == user_id,
                ClaimConceptLink.review_status == "confirmed",
                ClaimConceptLink.claim_id.in_(tuple(visible_claim_ids) or (-1,)),
                ClaimConceptLink.concept_id.in_(tuple(concept_ids) or (-1,)),
            )
            .order_by(ClaimConceptLink.id.asc())
        )).all())
        grouped_claim_links: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for link in claim_links:
            relation = CLAIM_CONCEPT_RELATION_TYPES.get(str(link.relation_type))
            if relation:
                grouped_claim_links[relation].append({
                    "claim_key": _key(user_id, "claim", int(link.claim_id)),
                    "concept_key": _key(user_id, "concept", int(link.concept_id)),
                    "sql_id": int(link.id),
                    "user_id": user_id,
                    "confidence": float(link.confidence),
                })
        for relation, rows in grouped_claim_links.items():
            await self.executor.execute(
                f"UNWIND $rows AS row MATCH (a:Claim {{key: row.claim_key}}), (b:Concept {{key: row.concept_key}}) "
                f"MERGE (a)-[r:{relation} {{sql_id: row.sql_id}}]->(b) "
                "SET r.user_id=row.user_id, r.confidence=row.confidence, r.relation_type=$relation_type",
                {"rows": rows, "relation_type": relation.casefold()},
            )

        relation_rows = list((await self.db.scalars(
            select(ClaimRelation)
            .where(
                ClaimRelation.user_id == user_id,
                ClaimRelation.review_status == "confirmed",
                ClaimRelation.from_claim_id.in_(tuple(visible_claim_ids) or (-1,)),
                ClaimRelation.to_claim_id.in_(tuple(visible_claim_ids) or (-1,)),
            )
            .order_by(ClaimRelation.id.asc())
        )).all())
        grouped_claim_relations: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for relation_row in relation_rows:
            relation = CLAIM_RELATION_TYPES.get(str(relation_row.relation_type))
            if relation:
                grouped_claim_relations[relation].append({
                    "from_key": _key(user_id, "claim", int(relation_row.from_claim_id)),
                    "to_key": _key(user_id, "claim", int(relation_row.to_claim_id)),
                    "sql_id": int(relation_row.id),
                    "user_id": user_id,
                    "confidence": float(relation_row.confidence),
                })
        for relation, rows in grouped_claim_relations.items():
            await self.executor.execute(
                f"UNWIND $rows AS row MATCH (a:Claim {{key: row.from_key}}), (b:Claim {{key: row.to_key}}) "
                f"MERGE (a)-[r:{relation} {{sql_id: row.sql_id}}]->(b) "
                "SET r.user_id=row.user_id, r.confidence=row.confidence, r.relation_type=$relation_type",
                {"rows": rows, "relation_type": relation.casefold()},
            )

        edge_rows = list((await self.db.scalars(
            select(ConceptEdge)
            .where(
                ConceptEdge.user_id == user_id,
                ConceptEdge.review_status == "confirmed",
                ConceptEdge.from_concept_id.in_(tuple(concept_ids) or (-1,)),
                ConceptEdge.to_concept_id.in_(tuple(concept_ids) or (-1,)),
            )
            .order_by(ConceptEdge.id.asc())
        )).all())
        grouped_edges: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for edge in edge_rows:
            relation = CONCEPT_RELATION_TYPES.get(str(edge.edge_type))
            if relation:
                grouped_edges[relation].append({
                    "from_key": _key(user_id, "concept", int(edge.from_concept_id)),
                    "to_key": _key(user_id, "concept", int(edge.to_concept_id)),
                    "sql_id": int(edge.id),
                    "user_id": user_id,
                    "confidence": float(edge.confidence),
                })
        for relation, rows in grouped_edges.items():
            await self.executor.execute(
                f"UNWIND $rows AS row MATCH (a:Concept {{key: row.from_key}}), (b:Concept {{key: row.to_key}}) "
                f"MERGE (a)-[r:{relation} {{sql_id: row.sql_id}}]->(b) "
                "SET r.user_id=row.user_id, r.confidence=row.confidence, r.edge_type=$edge_type",
                {"rows": rows, "edge_type": relation.casefold()},
            )

        return {
            "backend": self.backend,
            "user_id": user_id,
            "rebuilt": True,
            "sources": len(sources),
            "units": len(units),
            "claims": len(claims),
            "concepts": len(concepts),
            "claim_concept_links": len(claim_links),
            "claim_relations": len(relation_rows),
            "concept_edges": len(edge_rows),
        }

    async def delete_source(self, *, user_id: int, source_key: str) -> dict[str, Any]:
        rows = await self.executor.execute(
            "MATCH (s:Source {user_id:$user_id, source_key:$source_key}) "
            "OPTIONAL MATCH (s)-[:CONTAINS]->(u:Unit) "
            "OPTIONAL MATCH (u)-[:STATES]->(c:Claim) "
            "WITH collect(DISTINCT c) AS claims, collect(DISTINCT u) AS units, collect(DISTINCT s) AS sources "
            "FOREACH (n IN claims | DETACH DELETE n) "
            "FOREACH (n IN units | DETACH DELETE n) "
            "FOREACH (n IN sources | DETACH DELETE n) "
            "RETURN size(claims) AS claims, size(units) AS units, size(sources) AS sources",
            {"user_id": int(user_id), "source_key": str(source_key)},
        )
        counts = rows[0] if rows else {"claims": 0, "units": 0, "sources": 0}
        return {"backend": self.backend, "user_id": int(user_id), "source_key": str(source_key), **counts}

    async def source_claims(self, *, user_id: int, source_id: int, limit: int = 50) -> list[GraphHit]:
        _, max_hits = _bounds(1, limit)
        rows = await self.executor.execute(
            "MATCH (s:Source {user_id:$user_id, sql_id:$source_id})-[:CONTAINS]->(:Unit)-[:STATES]->(c:Claim {user_id:$user_id}) "
            "RETURN DISTINCT c.sql_id AS object_id, c.confidence AS confidence "
            "ORDER BY object_id ASC LIMIT $limit",
            {"user_id": int(user_id), "source_id": int(source_id), "limit": max_hits},
        )
        return [
            GraphHit("claim", int(row["object_id"]), "source_claims", 1, float(row.get("confidence") or 0.0), ({"type": "source", "id": int(source_id)},))
            for row in rows
        ]

    async def expand_claims(
        self,
        *,
        user_id: int,
        claim_ids: Sequence[int],
        patterns: Sequence[str],
        depth: int = 1,
        limit: int = 50,
    ) -> list[GraphHit]:
        max_depth, max_hits = _bounds(depth, limit)
        selected = _validate(patterns, CLAIM_PATTERNS)
        starts = _ids(claim_ids)
        if not starts:
            return []
        hits: dict[int, GraphHit] = {}
        if "shared_concept_claims" in selected:
            rows = await self.executor.execute(
                "MATCH (a:Claim {user_id:$user_id})-[r1:ABOUT|USES|APPLIES_TO|EXEMPLIFIES]->(concept:Concept {user_id:$user_id}) "
                "WHERE a.sql_id IN $claim_ids "
                "MATCH (target:Claim {user_id:$user_id})-[r2:ABOUT|USES|APPLIES_TO|EXEMPLIFIES]->(concept) "
                "WHERE NOT target.sql_id IN $claim_ids "
                "RETURN target.sql_id AS object_id, concept.sql_id AS concept_id, "
                "target.confidence AS claim_confidence, r2.confidence AS link_confidence "
                "ORDER BY link_confidence DESC, object_id ASC LIMIT $limit",
                {"user_id": int(user_id), "claim_ids": list(starts), "limit": max_hits},
            )
            for row in rows:
                confidence = min(float(row.get("claim_confidence") or 0.0), float(row.get("link_confidence") or 0.0))
                hit = GraphHit(
                    "claim", int(row["object_id"]), "shared_concept_claims", 1, confidence,
                    ({"type": "concept", "id": int(row["concept_id"])},),
                    {"concept_id": int(row["concept_id"])},
                )
                previous = hits.get(hit.object_id)
                if previous is None or hit.confidence > previous.confidence:
                    hits[hit.object_id] = hit
        if "direct_claim_relations" in selected:
            # Deliberately mirror SqlGraphStore hop-by-hop instead of using one
            # variable-length Cypher. SQL stops expanding once the *combined*
            # candidate pool reaches max_hits, so Shadow parity depends on the
            # same budget interaction with shared-concept hits.
            frontier = set(starts)
            visited = set(starts)
            for hop in range(1, max_depth + 1):
                if not frontier or len(hits) >= max_hits:
                    break
                rows = await self.executor.execute(
                    f"MATCH (a:Claim {{user_id:$user_id}})-[r:{_DIRECT_CLAIM_RELATION_CYPHER}]-(b:Claim {{user_id:$user_id}}) "
                    "WHERE a.sql_id IN $frontier AND NOT b.sql_id IN $visited AND r.user_id=$user_id "
                    "RETURN b.sql_id AS object_id, coalesce(r.confidence, 1.0) AS confidence, "
                    "r.sql_id AS relation_id, r.relation_type AS relation_type "
                    "ORDER BY confidence DESC, relation_id ASC",
                    {
                        "user_id": int(user_id),
                        "frontier": sorted(frontier),
                        "visited": sorted(visited),
                    },
                )
                next_frontier: set[int] = set()
                for row in rows:
                    object_id = int(row["object_id"])
                    if object_id in visited:
                        continue
                    next_frontier.add(object_id)
                    relation_id = int(row.get("relation_id") or 0)
                    relation_type = str(row.get("relation_type") or "")
                    # Like SqlGraphStore, a direct path overwrites any shared
                    # concept hit for the same Claim and multiple same-hop
                    # relations are processed in deterministic relation order.
                    hits[object_id] = GraphHit(
                        "claim", object_id, "direct_claim_relations", hop,
                        float(row.get("confidence") or 0.0),
                        ({"type": "claim_relation", "id": relation_id, "relation_type": relation_type},),
                        {"relation_id": relation_id, "relation_type": relation_type},
                    )
                visited.update(next_frontier)
                frontier = next_frontier
        return sorted(hits.values(), key=lambda row: (-row.confidence, row.depth, row.object_id))[:max_hits]

    async def expand_concepts(
        self,
        *,
        user_id: int,
        concept_ids: Sequence[int],
        patterns: Sequence[str],
        depth: int = 1,
        limit: int = 50,
    ) -> list[GraphHit]:
        max_depth, max_hits = _bounds(depth, limit)
        selected = _validate(patterns, CONCEPT_PATTERNS)
        starts = _ids(concept_ids)
        if not starts:
            return []
        hits: list[GraphHit] = []
        if "concept_structure" in selected:
            rows = await self.executor.execute(
                f"MATCH (start:Concept {{user_id:$user_id}}) WHERE start.sql_id IN $concept_ids "
                f"MATCH p=(start)-[rels:{_CONCEPT_RELATION_CYPHER}*1..{max_depth}]-(target:Concept {{user_id:$user_id}}) "
                "WHERE NOT target.sql_id IN $concept_ids AND all(r IN relationships(p) WHERE r.user_id=$user_id) "
                "WITH target, p, last(relationships(p)) AS edge "
                "RETURN target.sql_id AS object_id, length(p) AS depth, "
                "coalesce(edge.confidence, 1.0) AS confidence, edge.sql_id AS edge_id, edge.edge_type AS edge_type "
                "ORDER BY confidence DESC, depth ASC, object_id ASC LIMIT $limit",
                {"user_id": int(user_id), "concept_ids": list(starts), "limit": max_hits},
            )
            seen_concepts: set[int] = set()
            for row in rows:
                object_id = int(row["object_id"])
                if object_id in seen_concepts:
                    continue
                seen_concepts.add(object_id)
                hits.append(GraphHit(
                    "concept", object_id, "concept_structure", int(row.get("depth") or 1),
                    float(row.get("confidence") or 0.0),
                    ({"type": "concept_edge", "id": int(row.get("edge_id") or 0), "edge_type": str(row.get("edge_type") or "")},),
                ))
        if "personal_evidence_by_concept" in selected:
            # This path is not part of the Stage 6 Neo4j projection. It stays in
            # canonical SQL so desktop behavior and personal evidence semantics
            # remain unchanged while graph-only paths are evaluated in Shadow.
            hits.extend(await self._sql_fallback.expand_concepts(
                user_id=int(user_id),
                concept_ids=starts,
                patterns=("personal_evidence_by_concept",),
                depth=1,
                limit=max_hits,
            ))
        deduped: dict[tuple[str, int], GraphHit] = {}
        for hit in hits:
            key = (hit.object_type, hit.object_id)
            previous = deduped.get(key)
            if previous is None or hit.confidence > previous.confidence:
                deduped[key] = hit
        return sorted(deduped.values(), key=lambda row: (-row.confidence, row.depth, row.object_type, row.object_id))[:max_hits]

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
        """Return bounded, simple Concept paths using graph-native traversal.

        Neo4j only executes the topology search. Canonical Concept identity and
        confirmed source-evidence IDs are revalidated from SQL before results
        leave the GraphStore boundary.
        """
        user_id = int(user_id)
        starts = _ids(start_concept_ids)
        targets = _ids(target_concept_ids)
        if not starts or not targets:
            return []

        selected_relations = tuple(
            dict.fromkeys(str(value).strip() for value in relation_types if str(value).strip())
        )
        if not selected_relations:
            raise ValueError("concept path relation_types must not be empty")
        unknown = set(selected_relations) - set(CONCEPT_RELATION_TYPES)
        if unknown:
            raise ValueError(
                f"unsupported concept path relation type: {', '.join(sorted(unknown))}"
            )
        if direction not in {"outgoing", "incoming", "both"}:
            raise ValueError("unsupported concept path direction")

        max_depth = max(1, min(8, int(max_depth)))
        max_paths = max(1, min(20, int(limit)))

        requested_ids = tuple(dict.fromkeys((*starts, *targets)))
        owned_ids = {
            int(value)
            for value in (
                await self.db.scalars(
                    select(Concept.id).where(
                        Concept.user_id == user_id,
                        Concept.review_status == "confirmed",
                        Concept.id.in_(requested_ids),
                    )
                )
            ).all()
        }
        starts = tuple(value for value in starts if value in owned_ids)
        targets = tuple(value for value in targets if value in owned_ids)
        if not starts or not targets:
            return []

        paths: list[GraphPath] = []
        overlapping = tuple(value for value in starts if value in set(targets))
        for concept_id in overlapping[:max_paths]:
            node = GraphNodeRef("concept", int(concept_id))
            paths.append(
                GraphPath(
                    nodes=(node,),
                    edges=(),
                    score=1.0,
                    metadata={
                        "backend": self.backend,
                        "start_concept_id": int(concept_id),
                        "target_concept_id": int(concept_id),
                    },
                )
            )
        if len(paths) >= max_paths:
            return paths[:max_paths]

        traversal_starts = tuple(value for value in starts if value not in set(overlapping))
        traversal_targets = tuple(value for value in targets if value not in set(overlapping))
        if not traversal_starts or not traversal_targets:
            return paths[:max_paths]

        cypher_relation_types = "|".join(
            CONCEPT_RELATION_TYPES[value] for value in selected_relations
        )
        query = (
            "MATCH (start:Concept {user_id:$user_id}) "
            "WHERE start.sql_id IN $start_ids "
            "MATCH (target:Concept {user_id:$user_id}) "
            "WHERE target.sql_id IN $target_ids "
            f"MATCH p=(start)-[rels:{cypher_relation_types}*1..{max_depth}]-(target) "
            "WHERE all(n IN nodes(p) WHERE n.user_id=$user_id) "
            "AND all(r IN relationships(p) WHERE r.user_id=$user_id) "
            "AND all(n IN nodes(p) WHERE size([m IN nodes(p) WHERE m = n]) = 1) "
            "AND all(i IN range(0, size(relationships(p)) - 1) WHERE "
            "  type(relationships(p)[i]) = 'RELATED_TO' OR "
            "  $direction = 'both' OR "
            "  ($direction = 'outgoing' AND startNode(relationships(p)[i]) = nodes(p)[i]) OR "
            "  ($direction = 'incoming' AND endNode(relationships(p)[i]) = nodes(p)[i]) "
            ") "
            "WITH p, "
            "reduce(path_score=1.0, r IN relationships(p) | "
            "  path_score * coalesce(r.confidence, 1.0)" 
            ") AS path_score, "
            "[r IN relationships(p) | r.sql_id] AS edge_ids "
            "RETURN "
            "[n IN nodes(p) | n.sql_id] AS node_ids, "
            "[r IN relationships(p) | {"
            "  edge_id:r.sql_id, relation_type:r.edge_type, "
            "  from_id:startNode(r).sql_id, to_id:endNode(r).sql_id, "
            "  confidence:coalesce(r.confidence, 1.0)"
            "}] AS edge_rows, "
            "length(p) AS depth, path_score AS score, edge_ids "
            "ORDER BY depth ASC, score DESC, edge_ids ASC "
            "LIMIT $limit"
        )
        rows = await self.executor.execute(
            query,
            {
                "user_id": user_id,
                "start_ids": list(traversal_starts),
                "target_ids": list(traversal_targets),
                "direction": str(direction),
                "limit": max_paths - len(paths),
            },
        )

        edge_ids = {
            int(edge["edge_id"])
            for row in rows
            for edge in list(row.get("edge_rows") or [])
            if edge.get("edge_id") is not None
        }
        evidence_ids_by_edge: dict[int, list[int]] = defaultdict(list)
        if edge_ids:
            evidence_rows = (
                await self.db.execute(
                    select(
                        ConceptSourceEvidence.edge_id,
                        ConceptSourceEvidence.id,
                    )
                    .where(
                        ConceptSourceEvidence.user_id == user_id,
                        ConceptSourceEvidence.edge_id.in_(tuple(edge_ids)),
                        ConceptSourceEvidence.review_status == "confirmed",
                    )
                    .order_by(
                        ConceptSourceEvidence.edge_id.asc(),
                        ConceptSourceEvidence.confidence.desc(),
                        ConceptSourceEvidence.id.asc(),
                    )
                )
            ).all()
            for edge_id, evidence_id in evidence_rows:
                if edge_id is not None:
                    evidence_ids_by_edge[int(edge_id)].append(int(evidence_id))

        for row in rows:
            node_ids = tuple(int(value) for value in list(row.get("node_ids") or []))
            edge_rows = list(row.get("edge_rows") or [])
            if len(node_ids) < 2 or len(edge_rows) != len(node_ids) - 1:
                continue
            node_refs = tuple(GraphNodeRef("concept", value) for value in node_ids)
            edges: list[GraphEdgeRef] = []
            valid = True
            for index, edge_row in enumerate(edge_rows):
                edge_id = int(edge_row.get("edge_id") or 0)
                from_id = int(edge_row.get("from_id") or 0)
                to_id = int(edge_row.get("to_id") or 0)
                relation_type = str(edge_row.get("relation_type") or "").casefold()
                if (
                    edge_id <= 0
                    or from_id <= 0
                    or to_id <= 0
                    or relation_type not in selected_relations
                ):
                    valid = False
                    break
                from_node = GraphNodeRef("concept", from_id)
                to_node = GraphNodeRef("concept", to_id)
                traversed_forward = int(node_ids[index]) == from_id
                edges.append(
                    GraphEdgeRef(
                        edge_type="concept_edge",
                        edge_id=edge_id,
                        relation_type=relation_type,
                        from_node=from_node,
                        to_node=to_node,
                        directed=relation_type != "related_to",
                        traversed_forward=traversed_forward,
                        confidence=max(
                            0.0,
                            min(1.0, float(edge_row.get("confidence") or 0.0)),
                        ),
                        evidence_ids=tuple(evidence_ids_by_edge.get(edge_id, ())),
                    )
                )
            if not valid:
                continue
            paths.append(
                GraphPath(
                    nodes=node_refs,
                    edges=tuple(edges),
                    score=max(0.0, min(1.0, float(row.get("score") or 0.0))),
                    metadata={
                        "backend": self.backend,
                        "start_concept_id": int(node_ids[0]),
                        "target_concept_id": int(node_ids[-1]),
                    },
                )
            )

        return paths[:max_paths]

    async def health(self) -> dict[str, Any]:
        try:
            await self.executor.verify_connectivity()
        except Exception as exc:
            return {
                "ok": False,
                "backend": self.backend,
                "authoritative": False,
                "error": safe_exception_summary(exc),
            }
        return {
            "ok": True,
            "backend": self.backend,
            "authoritative": False,
            "database": str(settings.NEO4J_DATABASE),
        }
