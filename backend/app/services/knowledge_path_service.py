"""Explainable Knowledge/Learning Path built on graph execution + SQL truth.

Neo4j (when explicitly selected and ready) is responsible only for bounded path
search. Concept identity, learner state, and provenance are rehydrated from
canonical SQL before any product response is returned.
"""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.concept import Concept, ConceptEdge, ConceptSourceEvidence
from app.models.learner_model import LearnerEvidence, UserConceptState
from app.services.graph_store.base import (
    GraphCapabilityUnsupported,
    GraphNodeRef,
    GraphPath,
)
from app.services.graph_store.factory import create_graph_store
from app.utils.utc import to_utc_iso


SUPPORTED_PATH_RELATIONS = frozenset({"prerequisite_of", "related_to"})
DEFAULT_PATH_RELATIONS = ("prerequisite_of",)


@dataclass(frozen=True)
class KnowledgePathUnavailable(RuntimeError):
    """Safe capability-level failure for graph-native learning path."""

    reason: str

    def __str__(self) -> str:
        return self.reason


def _normalize_ids(values: Sequence[int], *, limit: int = 10) -> tuple[int, ...]:
    return tuple(dict.fromkeys(int(value) for value in values if int(value) > 0))[:limit]


def _learning_status(
    state: UserConceptState | None,
    *,
    evidence_total: int,
    mastery_threshold: float = 70.0,
    confidence_threshold: float = 0.45,
) -> str:
    if state is None or int(evidence_total) <= 0:
        return "unseen"
    if (
        float(state.mastery_estimate or 0.0) >= float(mastery_threshold)
        and float(state.confidence or 0.0) >= float(confidence_threshold)
    ):
        return "mastered"
    return "weak"


def _runtime_summary(store: Any) -> dict[str, Any]:
    diagnostics = dict(getattr(store, "last_diagnostics", {}) or {})
    requested = str(settings.GRAPH_BACKEND or "sql").strip().lower()
    effective = str(
        diagnostics.get("effective_backend")
        or getattr(store, "backend", requested)
        or requested
    )
    result: dict[str, Any] = {
        "requested_backend": requested,
        "effective_backend": effective,
    }
    route_reason = diagnostics.get("route_reason")
    if route_reason:
        result["route_reason"] = str(route_reason)
    return result


async def _load_requested_concepts(
    db: AsyncSession,
    *,
    user_id: int,
    concept_ids: Sequence[int],
) -> dict[int, Concept]:
    ids = tuple(dict.fromkeys(int(value) for value in concept_ids))
    if not ids:
        return {}
    rows = list(
        (
            await db.scalars(
                select(Concept).where(
                    Concept.user_id == int(user_id),
                    Concept.review_status == "confirmed",
                    Concept.id.in_(ids),
                )
            )
        ).all()
    )
    return {int(row.id): row for row in rows}


async def _learner_overlay(
    db: AsyncSession,
    *,
    user_id: int,
    concept_ids: Sequence[int],
) -> tuple[dict[int, UserConceptState], dict[int, dict[str, Any]]]:
    ids = tuple(dict.fromkeys(int(value) for value in concept_ids))
    if not ids:
        return {}, {}

    states = list(
        (
            await db.scalars(
                select(UserConceptState).where(
                    UserConceptState.user_id == int(user_id),
                    UserConceptState.concept_id.in_(ids),
                )
            )
        ).all()
    )
    state_by_concept = {int(row.concept_id): row for row in states}

    aggregates = (
        await db.execute(
            select(
                LearnerEvidence.concept_id,
                func.count(LearnerEvidence.id),
                func.sum(
                    case(
                        (LearnerEvidence.evidence_category == "direct", 1),
                        else_=0,
                    )
                ),
                func.max(LearnerEvidence.observed_at),
            )
            .where(
                LearnerEvidence.user_id == int(user_id),
                LearnerEvidence.concept_id.in_(ids),
            )
            .group_by(LearnerEvidence.concept_id)
        )
    ).all()
    evidence_by_concept: dict[int, dict[str, Any]] = {}
    for concept_id, total, direct, latest in aggregates:
        evidence_by_concept[int(concept_id)] = {
            "total": int(total or 0),
            "direct": int(direct or 0),
            "latest_observed_at": to_utc_iso(latest) if latest else None,
        }
    return state_by_concept, evidence_by_concept


async def _edge_overlay(
    db: AsyncSession,
    *,
    user_id: int,
    edge_ids: Sequence[int],
) -> tuple[dict[int, ConceptEdge], dict[int, list[ConceptSourceEvidence]]]:
    ids = tuple(dict.fromkeys(int(value) for value in edge_ids if int(value) > 0))
    if not ids:
        return {}, {}

    edges = list(
        (
            await db.scalars(
                select(ConceptEdge).where(
                    ConceptEdge.user_id == int(user_id),
                    ConceptEdge.review_status == "confirmed",
                    ConceptEdge.id.in_(ids),
                )
            )
        ).all()
    )
    edge_by_id = {int(row.id): row for row in edges}

    evidence_rows = list(
        (
            await db.scalars(
                select(ConceptSourceEvidence)
                .where(
                    ConceptSourceEvidence.user_id == int(user_id),
                    ConceptSourceEvidence.edge_id.in_(ids),
                    ConceptSourceEvidence.review_status == "confirmed",
                )
                .order_by(
                    ConceptSourceEvidence.edge_id.asc(),
                    ConceptSourceEvidence.confidence.desc(),
                    ConceptSourceEvidence.id.asc(),
                )
            )
        ).all()
    )
    evidence_by_edge: dict[int, list[ConceptSourceEvidence]] = defaultdict(list)
    for row in evidence_rows:
        if row.edge_id is not None and len(evidence_by_edge[int(row.edge_id)]) < 3:
            evidence_by_edge[int(row.edge_id)].append(row)
    return edge_by_id, evidence_by_edge


def _node_payload(
    concept: Concept,
    *,
    state: UserConceptState | None,
    learner_evidence: dict[str, Any],
    start_ids: set[int],
    target_id: int,
) -> dict[str, Any]:
    total = int(learner_evidence.get("total", 0) or 0)
    return {
        "concept_id": int(concept.id),
        "name": str(concept.name),
        "description": str(concept.description) if concept.description else None,
        "learning_status": _learning_status(state, evidence_total=total),
        "mastery_estimate": round(float(state.mastery_estimate), 2) if state is not None else 0.0,
        "confidence": round(float(state.confidence), 4) if state is not None else 0.0,
        "forgetting_risk": round(float(state.forgetting_risk), 4) if state is not None else 1.0,
        "reliability": round(float(state.reliability), 4) if state is not None else 0.0,
        "learner_evidence": {
            "total": total,
            "direct": int(learner_evidence.get("direct", 0) or 0),
            "latest_observed_at": learner_evidence.get("latest_observed_at"),
        },
        "is_start": int(concept.id) in start_ids,
        "is_target": int(concept.id) == int(target_id),
    }


def _edge_payload(
    edge: ConceptEdge,
    *,
    evidence_rows: Sequence[ConceptSourceEvidence],
    concept_by_id: dict[int, Concept],
    traversed_forward: bool,
) -> dict[str, Any]:
    evidence_payload = [
        {
            "source_type": str(row.source_type),
            "source_id": int(row.source_id),
            "source_version": int(row.source_version),
            "excerpt": str(row.excerpt),
            "confidence": round(float(row.confidence), 4),
        }
        for row in evidence_rows
    ]
    if evidence_payload:
        provenance_status = "confirmed_evidence"
    elif str(edge.source) == "manual":
        provenance_status = "confirmed_manual"
    else:
        provenance_status = "missing_evidence"

    from_concept = concept_by_id[int(edge.from_concept_id)]
    to_concept = concept_by_id[int(edge.to_concept_id)]
    return {
        "relation_type": str(edge.edge_type),
        "from": {
            "concept_id": int(from_concept.id),
            "name": str(from_concept.name),
        },
        "to": {
            "concept_id": int(to_concept.id),
            "name": str(to_concept.name),
        },
        "directed": str(edge.edge_type) != "related_to",
        "traversed_forward": bool(traversed_forward),
        "confidence": round(float(edge.confidence), 4),
        "source": str(edge.source),
        "provenance_status": provenance_status,
        "evidence": evidence_payload,
    }


async def build_learning_paths(
    db: AsyncSession,
    *,
    user_id: int,
    start_concept_ids: Sequence[int],
    target_concept_id: int,
    relation_types: Sequence[str] = DEFAULT_PATH_RELATIONS,
    max_depth: int = 6,
    limit: int = 3,
) -> dict[str, Any]:
    user_id = int(user_id)
    starts = _normalize_ids(start_concept_ids)
    target_id = int(target_concept_id)
    if not starts:
        raise ValueError("start_concept_ids must contain at least one Concept")
    if target_id <= 0:
        raise ValueError("target_concept_id must be positive")

    selected_relations = tuple(
        dict.fromkeys(str(value).strip() for value in relation_types if str(value).strip())
    )
    if not selected_relations:
        raise ValueError("relation_types must not be empty")
    unknown = set(selected_relations) - SUPPORTED_PATH_RELATIONS
    if unknown:
        raise ValueError(
            f"unsupported learning path relation type: {', '.join(sorted(unknown))}"
        )
    max_depth = max(1, min(8, int(max_depth)))
    limit = max(1, min(5, int(limit)))

    requested = tuple(dict.fromkeys((*starts, target_id)))
    requested_concepts = await _load_requested_concepts(
        db,
        user_id=user_id,
        concept_ids=requested,
    )
    missing = [value for value in requested if value not in requested_concepts]
    if missing:
        raise LookupError("knowledge_path_concept_not_found")

    if target_id in set(starts):
        graph_paths = [
            GraphPath(
                nodes=(GraphNodeRef("concept", target_id),),
                edges=(),
                score=1.0,
                metadata={
                    "backend": "canonical_sql",
                    "start_concept_id": target_id,
                    "target_concept_id": target_id,
                },
            )
        ]
        runtime = {
            "requested_backend": str(settings.GRAPH_BACKEND or "sql").strip().lower(),
            "effective_backend": "canonical_sql",
            "route_reason": "target_is_start",
        }
    else:
        store = create_graph_store(db)
        try:
            graph_paths = await store.find_concept_paths(
                user_id=user_id,
                start_concept_ids=starts,
                target_concept_ids=(target_id,),
                relation_types=selected_relations,
                direction="outgoing",
                max_depth=max_depth,
                limit=limit,
            )
        except GraphCapabilityUnsupported as exc:
            diagnostics = dict(getattr(store, "last_diagnostics", {}) or {})
            reason = str(diagnostics.get("route_reason") or str(exc) or "graph_capability_unavailable")
            raise KnowledgePathUnavailable(reason) from exc
        except Exception as exc:
            raise KnowledgePathUnavailable("graph_path_execution_unavailable") from exc
        runtime = _runtime_summary(store)

    node_ids = tuple(
        dict.fromkeys(
            int(node.object_id)
            for path in graph_paths
            for node in path.nodes
            if node.object_type == "concept"
        )
    )
    edge_ids = tuple(
        dict.fromkeys(int(edge.edge_id) for path in graph_paths for edge in path.edges)
    )

    concept_by_id = await _load_requested_concepts(
        db,
        user_id=user_id,
        concept_ids=node_ids,
    )
    if len(concept_by_id) != len(set(node_ids)):
        raise KnowledgePathUnavailable("path_rehydration_concept_mismatch")

    state_by_concept, learner_evidence = await _learner_overlay(
        db,
        user_id=user_id,
        concept_ids=node_ids,
    )
    edge_by_id, evidence_by_edge = await _edge_overlay(
        db,
        user_id=user_id,
        edge_ids=edge_ids,
    )
    if len(edge_by_id) != len(set(edge_ids)):
        raise KnowledgePathUnavailable("path_rehydration_edge_mismatch")

    start_set = set(starts)
    path_payloads: list[dict[str, Any]] = []
    for path in graph_paths:
        path_node_ids = [int(node.object_id) for node in path.nodes]
        if len(path_node_ids) != len(set(path_node_ids)):
            raise KnowledgePathUnavailable("path_rehydration_cycle")
        if len(path.edges) != max(0, len(path_node_ids) - 1):
            raise KnowledgePathUnavailable("path_rehydration_shape_mismatch")

        canonical_score = 1.0
        for index, graph_edge in enumerate(path.edges):
            sql_edge = edge_by_id[int(graph_edge.edge_id)]
            if str(sql_edge.edge_type) != str(graph_edge.relation_type):
                raise KnowledgePathUnavailable("path_rehydration_relation_mismatch")
            if str(sql_edge.edge_type) not in selected_relations:
                raise KnowledgePathUnavailable("path_rehydration_relation_not_allowed")
            left = int(path_node_ids[index])
            right = int(path_node_ids[index + 1])
            canonical_from = int(sql_edge.from_concept_id)
            canonical_to = int(sql_edge.to_concept_id)
            if str(sql_edge.edge_type) == "related_to":
                if {left, right} != {canonical_from, canonical_to}:
                    raise KnowledgePathUnavailable("path_rehydration_edge_mismatch")
            else:
                if not bool(graph_edge.traversed_forward):
                    raise KnowledgePathUnavailable("path_rehydration_direction_mismatch")
                if left != canonical_from or right != canonical_to:
                    raise KnowledgePathUnavailable("path_rehydration_edge_mismatch")
            canonical_score *= max(0.0, min(1.0, float(sql_edge.confidence)))

        path_nodes = [
            _node_payload(
                concept_by_id[int(node.object_id)],
                state=state_by_concept.get(int(node.object_id)),
                learner_evidence=learner_evidence.get(int(node.object_id), {}),
                start_ids=start_set,
                target_id=target_id,
            )
            for node in path.nodes
        ]
        path_edges = [
            _edge_payload(
                edge_by_id[int(edge.edge_id)],
                evidence_rows=evidence_by_edge.get(int(edge.edge_id), ()),
                concept_by_id=concept_by_id,
                traversed_forward=bool(edge.traversed_forward),
            )
            for edge in path.edges
        ]
        path_payloads.append(
            {
                "depth": int(path.depth),
                "score": round(float(canonical_score), 6),
                "nodes": path_nodes,
                "edges": path_edges,
            }
        )

    path_payloads.sort(
        key=lambda item: (
            int(item["depth"]),
            -float(item["score"]),
            tuple(int(node["concept_id"]) for node in item["nodes"]),
        )
    )
    path_payloads = path_payloads[:limit]

    target = requested_concepts[target_id]
    return {
        "status": "ok" if path_payloads else "no_path",
        "target": {
            "concept_id": int(target.id),
            "name": str(target.name),
        },
        "paths": path_payloads,
        "runtime": runtime,
    }
