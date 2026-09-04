"""Grounded, deterministic Association V2 over the current SQL Claim graph."""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Protocol, Sequence

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.concept import Concept, ConceptAlias
from app.models.knowledge import (
    Claim,
    ClaimConceptLink,
    ClaimEvidence,
    KnowledgeSource,
    KnowledgeSourceRevision,
    KnowledgeUnit,
)
from app.services.graph_store.base import GraphHit, GraphStore
from app.services.graph_store.factory import create_graph_store
from app.services.knowledge_embedding_service import get_knowledge_embedding_index
from app.services.sparse_knowledge_index import SparseKnowledgeIndex, create_sparse_knowledge_index


logger = logging.getLogger(__name__)
RANKER_VERSION = "association-feature-v1"
RANKER_WEIGHTS = {
    "dense_score": 0.24,
    "sparse_score": 0.19,
    "exact_score": 0.16,
    "graph_path_score": 0.21,
    "evidence_quality": 0.13,
    "source_diversity": 0.04,
    "personal_relevance": 0.03,
}
class ClaimPairJudge(Protocol):
    async def judge(self, *, anchor: dict[str, Any], related: dict[str, Any], evidence: dict[str, Any]) -> dict[str, Any]: ...


class AssociationSemanticReranker(Protocol):
    async def score_pairs(
        self,
        *,
        query: str,
        candidates: Sequence[dict[str, Any]],
    ) -> dict[int, float]: ...


@dataclass(frozen=True)
class QueryRepresentation:
    text: str
    concept_ids: tuple[int, ...]
    claim_ids: tuple[int, ...]
    concepts: tuple[dict[str, Any], ...]
    source_key: str | None = None


@dataclass
class _Candidate:
    claim_id: int
    scores: dict[str, float] = field(default_factory=dict)
    paths: list[GraphHit] = field(default_factory=list)
    anchor_concept_ids: set[int] = field(default_factory=set)


def _put(pool: dict[int, _Candidate], claim_id: int, channel: str, score: float, *, path: GraphHit | None = None, concept_ids: Sequence[int] = ()) -> None:
    candidate = pool.setdefault(int(claim_id), _Candidate(int(claim_id)))
    candidate.scores[channel] = max(float(candidate.scores.get(channel, 0.0)), max(0.0, min(1.0, float(score))))
    candidate.anchor_concept_ids.update(int(value) for value in concept_ids)
    if path is not None:
        candidate.paths.append(path)


async def _build_query_representation(db: AsyncSession, *, user_id: int, text: str, source_type: str | None, source_id: int | None, graph_store: GraphStore) -> QueryRepresentation:
    lowered = text.casefold()
    concepts = list((await db.scalars(select(Concept).where(Concept.user_id == user_id, Concept.review_status == "confirmed").order_by(Concept.id.asc()))).all())
    aliases = list((await db.scalars(select(ConceptAlias).where(ConceptAlias.user_id == user_id))).all())
    names: dict[int, list[str]] = {int(row.id): [str(row.name_normalized or row.name).casefold()] for row in concepts}
    for alias in aliases:
        names.setdefault(int(alias.concept_id), []).append(str(alias.alias_normalized or alias.alias).casefold())
    matched_ids = {
        concept_id for concept_id, values in names.items()
        if any(len(value) >= 2 and value in lowered for value in values)
    }
    claim_ids: set[int] = set()
    source_key = None
    if source_type and source_id:
        source = await db.scalar(select(KnowledgeSource).where(
            KnowledgeSource.user_id == user_id,
            KnowledgeSource.source_type == source_type,
            KnowledgeSource.source_record_id == int(source_id),
            KnowledgeSource.status == "active",
        ))
        if source is not None:
            source_key = str(source.source_key)
            claim_ids.update(hit.object_id for hit in await graph_store.source_claims(user_id=user_id, source_id=int(source.id), limit=50))
    if claim_ids:
        matched_ids.update(int(value) for value in (await db.scalars(select(ClaimConceptLink.concept_id).where(
            ClaimConceptLink.user_id == user_id,
            ClaimConceptLink.claim_id.in_(claim_ids),
            ClaimConceptLink.review_status == "confirmed",
        ))).all())
    by_id = {int(row.id): row for row in concepts}
    anchors = tuple({"id": value, "name": str(by_id[value].name)} for value in sorted(matched_ids) if value in by_id)
    return QueryRepresentation(text=text, concept_ids=tuple(sorted(matched_ids)), claim_ids=tuple(sorted(claim_ids)), concepts=anchors, source_key=source_key)


async def _visible_claim_rows(db: AsyncSession, *, user_id: int, claim_ids: Sequence[int] | None = None) -> list[tuple[Claim, KnowledgeSourceRevision, KnowledgeSource]]:
    statement = (
        select(Claim, KnowledgeSourceRevision, KnowledgeSource)
        .join(KnowledgeSourceRevision, KnowledgeSourceRevision.id == Claim.source_revision_id)
        .join(KnowledgeSource, KnowledgeSource.id == KnowledgeSourceRevision.knowledge_source_id)
        .where(
            Claim.user_id == user_id,
            Claim.review_status == "confirmed",
            Claim.lifecycle_status == "active",
            KnowledgeSourceRevision.user_id == user_id,
            KnowledgeSourceRevision.status == "current",
            KnowledgeSource.user_id == user_id,
            KnowledgeSource.status == "active",
            exists().where(ClaimEvidence.user_id == user_id, ClaimEvidence.claim_id == Claim.id),
        )
    )
    if claim_ids is not None:
        statement = statement.where(Claim.id.in_(tuple(claim_ids) or (-1,)))
    return list((await db.execute(statement.order_by(Claim.id.asc()))).all())


async def _concept_claim_ids(db: AsyncSession, *, user_id: int, concept_ids: Sequence[int]) -> list[tuple[int, int, float]]:
    if not concept_ids:
        return []
    rows = await db.execute(
        select(ClaimConceptLink.claim_id, ClaimConceptLink.concept_id, ClaimConceptLink.confidence)
        .join(Claim, Claim.id == ClaimConceptLink.claim_id)
        .join(KnowledgeSourceRevision, KnowledgeSourceRevision.id == Claim.source_revision_id)
        .join(KnowledgeSource, KnowledgeSource.id == KnowledgeSourceRevision.knowledge_source_id)
        .where(
            ClaimConceptLink.user_id == user_id,
            ClaimConceptLink.concept_id.in_(concept_ids),
            ClaimConceptLink.review_status == "confirmed",
            Claim.user_id == user_id, Claim.review_status == "confirmed", Claim.lifecycle_status == "active",
            KnowledgeSourceRevision.user_id == user_id, KnowledgeSourceRevision.status == "current",
            KnowledgeSource.user_id == user_id, KnowledgeSource.status == "active",
            exists().where(ClaimEvidence.user_id == user_id, ClaimEvidence.claim_id == Claim.id),
        )
    )
    return [(int(a), int(b), float(c)) for a, b, c in rows.all()]


async def associate(
    db: AsyncSession,
    *,
    user_id: int,
    text: str,
    source_type: str | None = None,
    source_id: int | None = None,
    limit: int = 5,
    graph_store: GraphStore | None = None,
    dense_index: Any | None = None,
    sparse_index: SparseKnowledgeIndex | None = None,
    semantic_reranker: AssociationSemanticReranker | None = None,
    judge: ClaimPairJudge | None = None,
) -> dict[str, Any]:
    """Return evidence-backed associations without committing the request transaction."""
    query_text = str(text or "").strip()
    if not query_text:
        raise ValueError("text 不能为空")
    user_id = int(user_id)
    max_results = max(1, min(10, int(limit)))
    graph = graph_store or create_graph_store(db)
    representation = await _build_query_representation(db, user_id=user_id, text=query_text, source_type=source_type, source_id=source_id, graph_store=graph)
    pool: dict[int, _Candidate] = {}
    degraded: dict[str, str] = {}
    graph_shadow_diagnostics: dict[str, Any] = {}

    for claim_id, concept_id, confidence in await _concept_claim_ids(db, user_id=user_id, concept_ids=representation.concept_ids):
        if claim_id not in representation.claim_ids:
            _put(pool, claim_id, "exact_score", confidence, concept_ids=(concept_id,))

    if representation.claim_ids:
        graph_hits: list[GraphHit] = []
        try:
            graph_hits = await graph.expand_claims(user_id=user_id, claim_ids=representation.claim_ids, patterns=("direct_claim_relations", "shared_concept_claims"), depth=2, limit=50)
            for hit in graph_hits:
                _put(pool, hit.object_id, "graph_path_score", hit.confidence * (1.0 if hit.path_type == "direct_claim_relations" else 0.82), path=hit, concept_ids=((hit.metadata.get("concept_id"),) if hit.metadata.get("concept_id") else ()))
        except Exception:
            degraded["graph"] = "unavailable"
        if graph_hits and settings.NEO4J_GRAPH_SHADOW and graph_store is None:
            try:
                from app.services.graph_shadow_service import compare_neo4j_claim_shadow

                graph_shadow_diagnostics["neo4j"] = await compare_neo4j_claim_shadow(
                    db,
                    user_id=user_id,
                    claim_ids=representation.claim_ids,
                    patterns=("direct_claim_relations", "shared_concept_claims"),
                    depth=2,
                    limit=50,
                    sql_hits=graph_hits,
                )
            except Exception as exc:
                graph_shadow_diagnostics["neo4j"] = {
                    "backend": "neo4j",
                    "status": "unavailable",
                    "error_type": exc.__class__.__name__,
                }

    dense = dense_index
    if dense is None and settings.KNOWLEDGE_EMBEDDING_ENABLED:
        dense = get_knowledge_embedding_index()
    if dense is not None:
        try:
            for row in await dense.query_claims(user_id=user_id, text=query_text, top_k=30):
                _put(pool, int(row["claim_id"]), "dense_score", float(row["score"]))
        except Exception:
            degraded["dense"] = "unavailable"

    sparse = sparse_index or create_sparse_knowledge_index(db)
    try:
        for row in await sparse.search(user_id=user_id, text=query_text, top_k=30):
            if int(row.claim_id) not in representation.claim_ids:
                _put(pool, int(row.claim_id), "sparse_score", float(row.score))
    except Exception:
        degraded["sparse"] = "unavailable"

    eligible = {
        int(claim.id): (claim, revision, source)
        for claim, revision, source in await _visible_claim_rows(
            db,
            user_id=user_id,
            claim_ids=tuple(pool),
        )
        if not representation.source_key
        or str(source.source_key) != str(representation.source_key)
    }
    candidate_ids = tuple(eligible)
    evidence_rows = list((await db.execute(
        select(ClaimEvidence, KnowledgeUnit).join(KnowledgeUnit, KnowledgeUnit.id == ClaimEvidence.knowledge_unit_id).where(
            ClaimEvidence.user_id == user_id,
            ClaimEvidence.claim_id.in_(candidate_ids or (-1,)),
            KnowledgeUnit.user_id == user_id,
        ).order_by(ClaimEvidence.claim_id.asc(), ClaimEvidence.confidence.desc(), ClaimEvidence.id.asc())
    )).all())
    evidence_by_claim: dict[int, list[tuple[ClaimEvidence, KnowledgeUnit]]] = {}
    for evidence, unit in evidence_rows:
        evidence_by_claim.setdefault(int(evidence.claim_id), []).append((evidence, unit))

    base_scores: dict[int, float] = {}
    ranked_candidates: dict[int, _Candidate] = {}
    for claim_id, candidate in pool.items():
        if claim_id not in eligible or not evidence_by_claim.get(claim_id):
            continue
        evidence_quality = max(float(row.confidence) for row, _ in evidence_by_claim[claim_id])
        candidate.scores["evidence_quality"] = evidence_quality
        candidate.scores["source_diversity"] = 1.0
        candidate.scores["personal_relevance"] = 1.0
        base_scores[claim_id] = sum(
            RANKER_WEIGHTS[key] * float(candidate.scores.get(key, 0.0))
            for key in RANKER_WEIGHTS
        )
        ranked_candidates[claim_id] = candidate

    semantic_scores: dict[int, float] = {}
    reranker_mode = "feature"
    reranker_diagnostics: dict[str, Any] = {
        "mode": "feature",
        "version": RANKER_VERSION,
        "latency_ms": 0.0,
    }
    if semantic_reranker is not None and ranked_candidates:
        reranker_started = time.perf_counter()
        try:
            raw_scores = await asyncio.wait_for(
                semantic_reranker.score_pairs(
                    query=query_text,
                    candidates=[
                        {
                            "claim_id": int(claim_id),
                            "claim": str(eligible[claim_id][0].statement),
                            "source_type": str(eligible[claim_id][2].source_type),
                            "source_id": int(eligible[claim_id][2].source_record_id),
                        }
                        for claim_id in sorted(ranked_candidates)
                    ],
                ),
                timeout=float(settings.KNOWLEDGE_RERANKER_TIMEOUT_SECONDS),
            )
            semantic_scores = {
                int(claim_id): max(0.0, min(1.0, float(score)))
                for claim_id, score in dict(raw_scores or {}).items()
                if int(claim_id) in ranked_candidates
            }
            if semantic_scores:
                reranker_mode = "semantic"
                reranker_diagnostics = dict(
                    getattr(semantic_reranker, "last_diagnostics", {}) or {}
                )
                reranker_diagnostics.setdefault("mode", "semantic")
                reranker_diagnostics.setdefault(
                    "latency_ms",
                    round((time.perf_counter() - reranker_started) * 1000.0, 3),
                )
        except Exception as exc:
            degraded["reranker"] = "feature_fallback"
            reranker_diagnostics = {
                "mode": "feature_fallback",
                "latency_ms": round(
                    (time.perf_counter() - reranker_started) * 1000.0,
                    3,
                ),
                "error_type": exc.__class__.__name__,
            }

    ranked: list[tuple[float, int, _Candidate]] = []
    for claim_id, candidate in ranked_candidates.items():
        base_score = float(base_scores[claim_id])
        semantic_score = semantic_scores.get(claim_id)
        if semantic_score is None:
            score = base_score
        else:
            candidate.scores["semantic_rerank"] = semantic_score
            score = 0.75 * base_score + 0.25 * semantic_score
        ranked.append((round(score, 12), claim_id, candidate))
    ranked.sort(key=lambda row: (-row[0], row[1]))

    output: list[dict[str, Any]] = []
    seen_evidence: set[str] = set()
    seen_sources: set[str] = set()
    for score, claim_id, candidate in ranked:
        claim, revision, source = eligible[claim_id]
        related_evidence: list[dict[str, Any]] = []
        for evidence, unit in evidence_by_claim[claim_id]:
            evidence_key = f"{source.source_key}:r{revision.revision}:u{unit.id}:{evidence.char_start}-{evidence.char_end}"
            if evidence_key in seen_evidence:
                continue
            related_evidence.append({"id": int(evidence.id), "evidence_key": evidence_key, "excerpt": str(evidence.excerpt), "locator": evidence.locator or {}, "confidence": float(evidence.confidence)})
        if not related_evidence or str(source.source_key) in seen_sources:
            continue
        best_path = sorted(candidate.paths, key=lambda hit: (hit.path_type != "direct_claim_relations", -hit.confidence, hit.object_id))[0] if candidate.paths else None
        relation = str(best_path.metadata.get("relation_type")) if best_path and best_path.metadata.get("relation_type") else "analogous_to"
        rationale = str(best_path.metadata.get("rationale") or "") if best_path else ""
        shared = rationale or ("由已确认的共同概念连接" if candidate.anchor_concept_ids else "由已落地的知识检索命中")
        item = {
            "anchor": {"claim": query_text, "claim_ids": list(representation.claim_ids), "concepts": list(representation.concepts)},
            "related": {"claim_id": claim_id, "claim": str(claim.statement), "source_type": str(source.source_type), "source_id": int(source.source_record_id), "source_title": str(source.title_snapshot)},
            "relation": relation,
            "shared_structure": shared,
            "important_difference": "",
            "path": [entry for hit in candidate.paths for entry in hit.path],
            "evidence": {
                "anchor": ([{"type": "source_claim", "claim_id": value} for value in representation.claim_ids] if representation.claim_ids else [{"type": "input_text", "text": query_text}]),
                "related": related_evidence,
            },
            "score": round(score, 6),
            "confidence": round(min(float(claim.confidence), max(row["confidence"] for row in related_evidence)), 6),
            "inferred": best_path is None or best_path.path_type != "direct_claim_relations",
            "ranker_version": RANKER_VERSION,
            "scores": {key: round(float(value), 6) for key, value in sorted(candidate.scores.items())},
        }
        if judge is not None:
            try:
                verdict = await judge.judge(anchor=item["anchor"], related=item["related"], evidence=item["evidence"])
                if not bool(verdict.get("worth_showing")):
                    continue
                for key in ("relation_type", "shared_structure", "important_difference", "confidence"):
                    if key in verdict:
                        item["relation" if key == "relation_type" else key] = verdict[key]
            except Exception:
                degraded["judge"] = "fallback_confirmed_paths_only"
                if best_path is None:
                    continue
        if settings.ASSOCIATION_MULTIHOP_EXPLANATION_ENABLED:
            try:
                from app.services.association_explanation_service import build_association_explanation

                explanation = await build_association_explanation(
                    db,
                    user_id=user_id,
                    anchor_concept_ids=representation.concept_ids,
                    related_claim_id=claim_id,
                    graph_store=graph,
                )
                if explanation is not None:
                    item["explanation"] = explanation
            except Exception:
                # Explanation is optional post-ranking enrichment. It must never
                # remove or reorder an otherwise valid Association result.
                degraded["explanation"] = "unavailable"
        seen_evidence.update(row["evidence_key"] for row in related_evidence)
        seen_sources.add(str(source.source_key))
        output.append(item)
        if len(output) >= max_results:
            break

    sparse_backend = str(getattr(sparse, "name", sparse.__class__.__name__))
    graph_backend = str(getattr(graph, "backend", "sql"))
    graph_runtime_diagnostics = dict(getattr(graph, "last_diagnostics", {}) or {})
    return {"associations": output, "diagnostics": {"mode": "v2", "degraded_sources": degraded, "candidate_counts": {"unified": len(pool), "eligible": len(eligible), "displayed": len(output)}, "reranker": reranker_mode, "reranker_diagnostics": reranker_diagnostics, "ranker_version": RANKER_VERSION, "graph_backend": graph_backend, "graph_runtime": graph_runtime_diagnostics, "graph_shadow": graph_shadow_diagnostics, "sparse_backend": sparse_backend}}
