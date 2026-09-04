"""Strictly user-scoped SQL implementation of the fixed graph paths."""
from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sqlalchemy import and_, exists, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models.concept import Concept, ConceptEdge, ConceptLink
from app.models.knowledge import (
    Claim,
    ClaimConceptLink,
    ClaimEvidence,
    ClaimRelation,
    KnowledgeSource,
    KnowledgeSourceRevision,
)
from app.services.graph_store.base import (
    CLAIM_PATTERNS,
    CONCEPT_PATTERNS,
    GraphCapabilityUnsupported,
    GraphHit,
    GraphPath,
    TraversalDirection,
)


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


def _visible_claim(claim: Any, revision: Any, source: Any, *, user_id: int):
    return and_(
        claim.user_id == user_id,
        claim.review_status == "confirmed",
        claim.lifecycle_status == "active",
        revision.id == claim.source_revision_id,
        revision.user_id == user_id,
        revision.status == "current",
        source.id == revision.knowledge_source_id,
        source.user_id == user_id,
        source.status == "active",
        exists().where(
            ClaimEvidence.claim_id == claim.id,
            ClaimEvidence.user_id == user_id,
        ),
    )


class SqlGraphStore:
    """Query only the product-safe graph; SQL remains authoritative."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def _eligible_claim_ids(self, user_id: int, claim_ids: Sequence[int]) -> set[int]:
        ids = _ids(claim_ids)
        if not ids:
            return set()
        rows = await self.db.scalars(
            select(Claim.id)
            .join(KnowledgeSourceRevision, KnowledgeSourceRevision.id == Claim.source_revision_id)
            .join(KnowledgeSource, KnowledgeSource.id == KnowledgeSourceRevision.knowledge_source_id)
            .where(Claim.id.in_(ids), _visible_claim(Claim, KnowledgeSourceRevision, KnowledgeSource, user_id=user_id))
        )
        return {int(value) for value in rows.all()}

    async def expand_claims(self, *, user_id: int, claim_ids: Sequence[int], patterns: Sequence[str], depth: int = 1, limit: int = 50) -> list[GraphHit]:
        max_depth, max_hits = _bounds(depth, limit)
        selected = _validate(patterns, CLAIM_PATTERNS)
        starts = await self._eligible_claim_ids(int(user_id), claim_ids)
        if not starts:
            return []
        hits: dict[int, GraphHit] = {}

        if "shared_concept_claims" in selected:
            anchor_link = aliased(ClaimConceptLink)
            target_link = aliased(ClaimConceptLink)
            rows = await self.db.execute(
                select(target_link.claim_id, target_link.concept_id, target_link.confidence, Claim.confidence)
                .join(anchor_link, anchor_link.concept_id == target_link.concept_id)
                .join(Claim, Claim.id == target_link.claim_id)
                .join(KnowledgeSourceRevision, KnowledgeSourceRevision.id == Claim.source_revision_id)
                .join(KnowledgeSource, KnowledgeSource.id == KnowledgeSourceRevision.knowledge_source_id)
                .where(
                    anchor_link.user_id == int(user_id),
                    anchor_link.claim_id.in_(starts),
                    anchor_link.review_status == "confirmed",
                    target_link.user_id == int(user_id),
                    target_link.review_status == "confirmed",
                    target_link.claim_id.not_in(starts),
                    _visible_claim(Claim, KnowledgeSourceRevision, KnowledgeSource, user_id=int(user_id)),
                )
                .order_by(target_link.confidence.desc(), target_link.claim_id.asc())
                .limit(max_hits)
            )
            for claim_id, concept_id, link_confidence, claim_confidence in rows.all():
                confidence = min(float(link_confidence), float(claim_confidence))
                hit = GraphHit("claim", int(claim_id), "shared_concept_claims", 1, confidence, ({"type": "concept", "id": int(concept_id)},), {"concept_id": int(concept_id)})
                previous = hits.get(int(claim_id))
                if previous is None or hit.confidence > previous.confidence:
                    hits[int(claim_id)] = hit

        if "direct_claim_relations" in selected:
            frontier = set(starts)
            visited = set(starts)
            for hop in range(1, max_depth + 1):
                if not frontier or len(hits) >= max_hits:
                    break
                relations = list((await self.db.scalars(
                    select(ClaimRelation).where(
                        ClaimRelation.user_id == int(user_id),
                        ClaimRelation.review_status == "confirmed",
                        or_(ClaimRelation.from_claim_id.in_(frontier), ClaimRelation.to_claim_id.in_(frontier)),
                    ).order_by(ClaimRelation.confidence.desc(), ClaimRelation.id.asc())
                )).all())
                candidates = {
                    int(row.to_claim_id if int(row.from_claim_id) in frontier else row.from_claim_id)
                    for row in relations
                } - visited
                eligible = await self._eligible_claim_ids(int(user_id), tuple(candidates))
                next_frontier: set[int] = set()
                for row in relations:
                    candidate = int(row.to_claim_id if int(row.from_claim_id) in frontier else row.from_claim_id)
                    if candidate not in eligible or candidate in visited:
                        continue
                    next_frontier.add(candidate)
                    hits[candidate] = GraphHit(
                        "claim", candidate, "direct_claim_relations", hop, float(row.confidence),
                        ({"type": "claim_relation", "id": int(row.id), "relation_type": str(row.relation_type)},),
                        {"relation_id": int(row.id), "relation_type": str(row.relation_type), "rationale": str(row.rationale or "")},
                    )
                visited.update(next_frontier)
                frontier = next_frontier

        return sorted(hits.values(), key=lambda row: (-row.confidence, row.depth, row.object_id))[:max_hits]

    async def expand_concepts(self, *, user_id: int, concept_ids: Sequence[int], patterns: Sequence[str], depth: int = 1, limit: int = 50) -> list[GraphHit]:
        max_depth, max_hits = _bounds(depth, limit)
        selected = _validate(patterns, CONCEPT_PATTERNS)
        owned = set((await self.db.scalars(select(Concept.id).where(Concept.user_id == int(user_id), Concept.review_status == "confirmed", Concept.id.in_(_ids(concept_ids) or (-1,))))).all())
        if not owned:
            return []
        hits: dict[tuple[str, int], GraphHit] = {}
        if "concept_structure" in selected:
            frontier = {int(value) for value in owned}
            visited = set(frontier)
            for hop in range(1, max_depth + 1):
                edges = list((await self.db.scalars(select(ConceptEdge).where(
                    ConceptEdge.user_id == int(user_id), ConceptEdge.review_status == "confirmed",
                    ConceptEdge.edge_type.in_(("prerequisite_of", "related_to")),
                    or_(ConceptEdge.from_concept_id.in_(frontier), ConceptEdge.to_concept_id.in_(frontier)),
                ).order_by(ConceptEdge.confidence.desc(), ConceptEdge.id.asc()))).all())
                candidates = {int(e.to_concept_id if int(e.from_concept_id) in frontier else e.from_concept_id) for e in edges} - visited
                allowed = set((await self.db.scalars(select(Concept.id).where(Concept.user_id == int(user_id), Concept.review_status == "confirmed", Concept.id.in_(candidates or (-1,))))).all())
                for edge in edges:
                    candidate = int(edge.to_concept_id if int(edge.from_concept_id) in frontier else edge.from_concept_id)
                    if candidate in allowed:
                        hits[("concept", candidate)] = GraphHit("concept", candidate, "concept_structure", hop, float(edge.confidence), ({"type": "concept_edge", "id": int(edge.id), "edge_type": str(edge.edge_type)},))
                visited.update(int(value) for value in allowed)
                frontier = {int(value) for value in allowed}
                if not frontier:
                    break
        if "personal_evidence_by_concept" in selected:
            links = list((await self.db.scalars(select(ConceptLink).where(ConceptLink.user_id == int(user_id), ConceptLink.concept_id.in_(owned), ConceptLink.target_type.in_(("note", "wrong_question"))).order_by(ConceptLink.id.asc()).limit(max_hits))).all())
            for link in links:
                key = (str(link.target_type), int(link.target_id))
                hits[key] = GraphHit(str(link.target_type), int(link.target_id), "personal_evidence_by_concept", 1, 1.0, ({"type": "concept", "id": int(link.concept_id)},), {"concept_id": int(link.concept_id)})
        return sorted(hits.values(), key=lambda row: (-row.confidence, row.depth, row.object_type, row.object_id))[:max_hits]

    async def source_claims(self, *, user_id: int, source_id: int, limit: int = 50) -> list[GraphHit]:
        _, max_hits = _bounds(1, limit)
        rows = await self.db.scalars(
            select(Claim)
            .join(KnowledgeSourceRevision, KnowledgeSourceRevision.id == Claim.source_revision_id)
            .join(KnowledgeSource, KnowledgeSource.id == KnowledgeSourceRevision.knowledge_source_id)
            .where(KnowledgeSource.id == int(source_id), _visible_claim(Claim, KnowledgeSourceRevision, KnowledgeSource, user_id=int(user_id)))
            .order_by(Claim.id.asc()).limit(max_hits)
        )
        return [GraphHit("claim", int(row.id), "source_claims", 1, float(row.confidence), ({"type": "source", "id": int(source_id)},)) for row in rows.all()]

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
        # Stage 7 intentionally does not turn SqlGraphStore into a generic graph
        # engine. Existing bounded/fixed neighborhood queries remain available,
        # while graph-native path search is introduced by a backend that can
        # express it naturally. A product-level caller may choose a narrower SQL
        # fallback later, but must do so explicitly rather than silently changing
        # path semantics.
        del user_id, start_concept_ids, target_concept_ids, relation_types, direction, max_depth, limit
        raise GraphCapabilityUnsupported("concept_path_search_not_supported_by_sql_backend")

    async def rebuild_user(self, *, user_id: int) -> dict[str, Any]:
        return {"backend": "sql", "user_id": int(user_id), "rebuilt": False, "authoritative": True}

    async def delete_source(self, *, user_id: int, source_key: str) -> dict[str, Any]:
        owned = await self.db.scalar(select(KnowledgeSource.id).where(KnowledgeSource.user_id == int(user_id), KnowledgeSource.source_key == str(source_key)))
        return {"backend": "sql", "deleted": False, "authoritative": True, "source_exists": owned is not None}

    async def health(self) -> dict[str, Any]:
        return {"ok": True, "backend": "sql", "authoritative": True}
