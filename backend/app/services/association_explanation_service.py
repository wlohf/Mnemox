"""Presentation-safe multi-hop explanations for Association V2.

Graph execution may discover topology, but every returned Concept/Edge and all
provenance are rehydrated from user-scoped Canonical SQL before an explanation
is exposed to the product surface.
"""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.concept import Concept, ConceptEdge, ConceptSourceEvidence
from app.models.knowledge import ClaimConceptLink
from app.services.graph_store.base import GraphPath, GraphStore


EXPLANATION_RELATIONS = ("prerequisite_of", "related_to")


def _ids(values: Sequence[int]) -> tuple[int, ...]:
    return tuple(dict.fromkeys(int(value) for value in values if int(value) > 0))


async def _confirmed_concepts(
    db: AsyncSession,
    *,
    user_id: int,
    concept_ids: Sequence[int],
) -> dict[int, Concept]:
    ids = _ids(concept_ids)
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


async def _related_concepts(
    db: AsyncSession,
    *,
    user_id: int,
    related_claim_id: int,
) -> tuple[int, ...]:
    rows = await db.execute(
        select(ClaimConceptLink.concept_id)
        .join(Concept, Concept.id == ClaimConceptLink.concept_id)
        .where(
            ClaimConceptLink.user_id == int(user_id),
            ClaimConceptLink.claim_id == int(related_claim_id),
            ClaimConceptLink.review_status == "confirmed",
            Concept.user_id == int(user_id),
            Concept.review_status == "confirmed",
        )
        .order_by(ClaimConceptLink.confidence.desc(), ClaimConceptLink.id.asc())
    )
    return _ids([int(value) for value in rows.scalars().all()])


async def _rehydrate_path(
    db: AsyncSession,
    *,
    user_id: int,
    path: GraphPath,
) -> dict[str, Any] | None:
    node_ids = _ids(
        [int(node.object_id) for node in path.nodes if str(node.object_type) == "concept"]
    )
    if len(node_ids) != len(path.nodes) or len(node_ids) != len(set(node_ids)):
        return None
    if len(path.edges) != max(0, len(path.nodes) - 1):
        return None

    concept_by_id = await _confirmed_concepts(db, user_id=user_id, concept_ids=node_ids)
    if len(concept_by_id) != len(node_ids):
        return None

    edge_ids = _ids([int(edge.edge_id) for edge in path.edges])
    edge_rows = list(
        (
            await db.scalars(
                select(ConceptEdge).where(
                    ConceptEdge.user_id == int(user_id),
                    ConceptEdge.review_status == "confirmed",
                    ConceptEdge.id.in_(edge_ids or (-1,)),
                )
            )
        ).all()
    )
    edge_by_id = {int(row.id): row for row in edge_rows}
    if len(edge_by_id) != len(edge_ids):
        return None

    evidence_by_edge: dict[int, list[ConceptSourceEvidence]] = defaultdict(list)
    if edge_ids:
        evidence_rows = list(
            (
                await db.scalars(
                    select(ConceptSourceEvidence)
                    .where(
                        ConceptSourceEvidence.user_id == int(user_id),
                        ConceptSourceEvidence.edge_id.in_(edge_ids),
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
        for row in evidence_rows:
            if row.edge_id is not None and len(evidence_by_edge[int(row.edge_id)]) < 2:
                evidence_by_edge[int(row.edge_id)].append(row)

    steps: list[dict[str, Any]] = [{"type": "anchor", "label": "当前内容"}]
    evidence_payload: list[dict[str, Any]] = []
    relation_names: list[str] = []

    for index, node_id in enumerate(node_ids):
        concept = concept_by_id[node_id]
        steps.append({"type": "concept", "name": str(concept.name)})
        if index >= len(path.edges):
            continue

        graph_edge = path.edges[index]
        sql_edge = edge_by_id.get(int(graph_edge.edge_id))
        if sql_edge is None:
            return None
        relation_type = str(sql_edge.edge_type)
        if relation_type != str(graph_edge.relation_type) or relation_type not in EXPLANATION_RELATIONS:
            return None

        left = int(node_ids[index])
        right = int(node_ids[index + 1])
        canonical_from = int(sql_edge.from_concept_id)
        canonical_to = int(sql_edge.to_concept_id)
        if relation_type == "related_to":
            if {left, right} != {canonical_from, canonical_to}:
                return None
        else:
            forward = left == canonical_from and right == canonical_to
            reverse = left == canonical_to and right == canonical_from
            if not (forward or reverse):
                return None
            if bool(graph_edge.traversed_forward) != bool(forward):
                return None

        evidence_rows = evidence_by_edge.get(int(sql_edge.id), [])
        if evidence_rows:
            provenance_status = "confirmed_evidence"
        elif str(sql_edge.source) == "manual":
            provenance_status = "confirmed_manual"
        else:
            provenance_status = "missing_evidence"

        steps.append(
            {
                "type": "relation",
                "relation_type": relation_type,
                "directed": relation_type != "related_to",
                "traversed_forward": bool(graph_edge.traversed_forward),
                "provenance_status": provenance_status,
            }
        )
        relation_names.append(relation_type)
        for row in evidence_rows:
            evidence_payload.append(
                {
                    "source_type": str(row.source_type),
                    "source_id": int(row.source_id),
                    "source_version": int(row.source_version),
                    "excerpt": str(row.excerpt),
                    "confidence": round(float(row.confidence), 4),
                }
            )

    steps.append({"type": "related_claim", "label": "候选知识"})
    first_name = str(concept_by_id[node_ids[0]].name)
    last_name = str(concept_by_id[node_ids[-1]].name)
    if not relation_names:
        summary = f"共同关联到「{first_name}」"
    elif len(relation_names) == 1:
        summary = f"「{first_name}」通过 {relation_names[0]} 连接到「{last_name}」"
    else:
        summary = f"「{first_name}」通过 {' → '.join(relation_names)} 连接到「{last_name}」"

    return {
        "kind": "graph_path",
        "summary": summary,
        "steps": steps,
        "evidence": evidence_payload,
    }


async def build_association_explanation(
    db: AsyncSession,
    *,
    user_id: int,
    anchor_concept_ids: Sequence[int],
    related_claim_id: int,
    graph_store: GraphStore,
    max_depth: int = 4,
) -> dict[str, Any] | None:
    """Return one verified presentation-safe explanation, or ``None``.

    Explanation is optional enrichment: any graph/runtime failure is intentionally
    converted to no explanation so Association ranking remains available.
    """
    anchors = _ids(anchor_concept_ids)
    if not anchors:
        return None

    anchor_by_id = await _confirmed_concepts(db, user_id=int(user_id), concept_ids=anchors)
    anchors = tuple(value for value in anchors if value in anchor_by_id)
    if not anchors:
        return None

    related_ids = await _related_concepts(
        db,
        user_id=int(user_id),
        related_claim_id=int(related_claim_id),
    )
    if not related_ids:
        return None

    shared = sorted(set(anchors) & set(related_ids))
    if shared:
        concept = anchor_by_id.get(shared[0])
        if concept is None:
            related_by_id = await _confirmed_concepts(
                db,
                user_id=int(user_id),
                concept_ids=(shared[0],),
            )
            concept = related_by_id.get(shared[0])
        if concept is None:
            return None
        return {
            "kind": "graph_path",
            "summary": f"共同关联到「{concept.name}」",
            "steps": [
                {"type": "anchor", "label": "当前内容"},
                {"type": "concept", "name": str(concept.name)},
                {"type": "related_claim", "label": "候选知识"},
            ],
            "evidence": [],
        }

    try:
        paths = await graph_store.find_concept_paths(
            user_id=int(user_id),
            start_concept_ids=anchors,
            target_concept_ids=related_ids,
            relation_types=EXPLANATION_RELATIONS,
            direction="both",
            max_depth=max(1, min(6, int(max_depth))),
            limit=3,
        )
    except Exception:
        return None

    for path in paths:
        explanation = await _rehydrate_path(db, user_id=int(user_id), path=path)
        if explanation is not None:
            return explanation
    return None
