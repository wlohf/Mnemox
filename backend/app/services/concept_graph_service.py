"""Canonical SQL concept identity, review, provenance and prerequisite gaps."""
from __future__ import annotations

import re
from typing import Any

from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.concept import (
    Concept,
    ConceptAlias,
    ConceptAuditEvent,
    ConceptEdge,
    ConceptLink,
    ConceptSourceEvidence,
)
from app.models.learner_model import LearnerEvidence, ProjectionOutbox, UserConceptState
from app.models.material import Chapter, Material
from app.models.question import WrongQuestion
from app.models.retrieval import RetrievalProjection
from app.services.concept_service import (
    MAX_NAME_LENGTH,
    REVIEW_STATUSES,
    add_edge,
    get_concept_neighborhood,
    link_concept,
    normalize_concept_name,
    record_concept_source_evidence,
    upsert_concept,
)
from app.services.learner_model_service import recompute_concept_state


MAX_MATERIAL_CONCEPTS = 40
_TERM = r"[A-Za-z\u4e00-\u9fff][A-Za-z0-9\u4e00-\u9fff_+./ -]{1,58}"
_HEADING = re.compile(r"^#{1,6}\s+(?P<name>.{2,60}?)\s*#*\s*$", re.MULTILINE)
_DEFINITION = re.compile(rf"^\s*(?:[-*]\s*)?(?P<name>{_TERM})\s*[：:]\s*(?P<body>.{{4,240}})$", re.MULTILINE)
_INLINE = re.compile(r"(?:\*\*|`)(?P<name>[A-Za-z\u4e00-\u9fff][^`*\n]{1,58})(?:\*\*|`)")
_ALIAS = re.compile(rf"(?P<name>{_TERM})\s*[（(](?P<alias>[^()（）\n]{{2,80}})[）)]")
_ARROW = re.compile(rf"(?P<first>{_TERM}?)\s*(?:→|->)\s*(?P<second>{_TERM})(?=$|[，。；;\n])")
_PREREQUISITE = re.compile(
    rf"(?P<first>{_TERM}?)\s*(?:是|为)\s*(?P<second>{_TERM}?)\s*(?:的)?先修(?:知识|概念|条件)?"
)


async def _owned_concept(db: AsyncSession, user_id: int, concept_id: int) -> Concept:
    concept = await db.scalar(select(Concept).where(Concept.id == int(concept_id), Concept.user_id == int(user_id)))
    if concept is None:
        raise LookupError("概念不存在")
    return concept


async def _audit(
    db: AsyncSession,
    user_id: int,
    concept_id: int | None,
    operation: str,
    *,
    payload: dict[str, Any] | None = None,
    actor: str = "user",
) -> None:
    db.add(
        ConceptAuditEvent(
            user_id=int(user_id),
            concept_id=(int(concept_id) if concept_id is not None else None),
            operation=str(operation)[:40],
            actor=str(actor)[:30],
            payload=dict(payload or {}),
        )
    )
    await db.flush()


async def add_concept_alias(
    db: AsyncSession,
    user_id: int,
    concept_id: int,
    alias: str,
    *,
    source: str = "manual",
    audit: bool = True,
) -> dict[str, Any]:
    concept = await _owned_concept(db, user_id, concept_id)
    clean_alias = re.sub(r"\s+", " ", str(alias or "")).strip()[:120]
    normalized = normalize_concept_name(clean_alias)
    if len(normalized) < 2:
        raise ValueError("概念别名至少需要两个字符")
    if normalized == concept.name_normalized:
        return {"alias": concept.name, "concept_id": int(concept.id), "created": False}
    other_concept = await db.scalar(
        select(Concept.id).where(Concept.user_id == user_id, Concept.name_normalized == normalized)
    )
    if other_concept is not None and int(other_concept) != int(concept.id):
        raise ValueError("该名称已属于另一个概念，请先合并概念")
    existing = await db.scalar(
        select(ConceptAlias).where(ConceptAlias.user_id == user_id, ConceptAlias.alias_normalized == normalized)
    )
    if existing is not None:
        if int(existing.concept_id) != int(concept.id):
            raise ValueError("该别名已属于另一个概念")
        return {"id": int(existing.id), "alias": existing.alias, "concept_id": int(concept.id), "created": False}
    row = ConceptAlias(
        user_id=int(user_id), concept_id=int(concept.id), alias=clean_alias,
        alias_normalized=normalized, source=str(source)[:40],
    )
    db.add(row)
    await db.flush()
    if audit:
        await _audit(db, user_id, int(concept.id), "alias_added", payload={"alias": clean_alias, "source": source})
    return {"id": int(row.id), "alias": row.alias, "concept_id": int(concept.id), "created": True}


async def rename_concept(
    db: AsyncSession,
    user_id: int,
    concept_id: int,
    *,
    name: str,
    description: str | None = None,
) -> dict[str, Any]:
    concept = await _owned_concept(db, user_id, concept_id)
    clean_name = re.sub(r"\s+", " ", str(name or "")).strip()[:MAX_NAME_LENGTH]
    normalized = normalize_concept_name(clean_name)
    if len(normalized) < 2:
        raise ValueError("概念名称至少需要两个字符")
    other = await db.scalar(
        select(Concept.id).where(
            Concept.user_id == user_id, Concept.name_normalized == normalized, Concept.id != int(concept.id),
        )
    )
    if other is not None:
        raise ValueError("该名称已属于另一个概念，请使用合并操作")
    conflicting_alias = await db.scalar(
        select(ConceptAlias).where(ConceptAlias.user_id == user_id, ConceptAlias.alias_normalized == normalized)
    )
    if conflicting_alias is not None and int(conflicting_alias.concept_id) != int(concept.id):
        raise ValueError("该名称已是另一个概念的别名")
    if conflicting_alias is not None:
        await db.delete(conflicting_alias)
        await db.flush()
    previous_name = concept.name
    concept.name = clean_name
    concept.name_normalized = normalized
    if description is not None:
        concept.description = str(description).strip()[:500] or None
    await db.flush()
    if normalize_concept_name(previous_name) != normalized:
        await add_concept_alias(db, user_id, int(concept.id), previous_name, source="rename", audit=False)
    await _audit(
        db, user_id, int(concept.id), "renamed", payload={"previous_name": previous_name, "name": clean_name},
    )
    return await get_concept_detail(db, user_id, int(concept.id))


async def _source_version(db: AsyncSession, user_id: int, material_id: int) -> int:
    version = await db.scalar(
        select(func.max(RetrievalProjection.source_version)).where(
            RetrievalProjection.user_id == int(user_id),
            RetrievalProjection.source_type == "material",
            RetrievalProjection.source_id == int(material_id),
        )
    )
    return max(1, int(version or 1))


def _extract_candidates(content: str) -> tuple[list[tuple[str, str]], list[tuple[str, str]], list[tuple[str, str, str]]]:
    text = str(content or "")[:80_000]
    candidates: dict[str, tuple[str, str]] = {}
    aliases: list[tuple[str, str]] = []
    relations: list[tuple[str, str, str]] = []

    def add(name: str, excerpt: str) -> None:
        clean = re.sub(r"\s+", " ", str(name or "")).strip(" -–—:：#")[:MAX_NAME_LENGTH]
        normalized = normalize_concept_name(clean)
        if len(normalized) >= 2 and len(candidates) < MAX_MATERIAL_CONCEPTS:
            candidates.setdefault(normalized, (clean, str(excerpt).strip()[:280]))

    for match in _HEADING.finditer(text):
        add(match.group("name"), match.group(0))
    for match in _DEFINITION.finditer(text):
        add(match.group("name"), match.group(0))
    for match in _INLINE.finditer(text):
        add(match.group("name"), match.group(0))
    for match in _ALIAS.finditer(text):
        name = match.group("name").strip()
        alias = match.group("alias").strip()
        if "：" in name or ":" in name or len(alias) > 70:
            continue
        add(name, match.group(0))
        aliases.append((name, alias))
    for pattern in (_ARROW, _PREREQUISITE):
        for match in pattern.finditer(text):
            first, second = match.group("first").strip(), match.group("second").strip()
            add(first, match.group(0))
            add(second, match.group(0))
            relations.append((first, second, match.group(0)))
    return list(candidates.values()), aliases, relations


async def forget_material_concepts(
    db: AsyncSession,
    user_id: int,
    material_id: int,
    *,
    remove_chapter_links: bool = False,
) -> dict[str, int]:
    """Remove only the derived source facts owned by the deleted/updated material."""
    evidence = list((
        await db.execute(
            select(ConceptSourceEvidence).where(
                ConceptSourceEvidence.user_id == int(user_id),
                ConceptSourceEvidence.source_type == "material",
                ConceptSourceEvidence.source_id == int(material_id),
            )
        )
    ).scalars().all())
    concept_ids = {int(row.concept_id) for row in evidence}
    edge_ids = {int(row.edge_id) for row in evidence if row.edge_id is not None}
    for row in evidence:
        await db.delete(row)
    await db.execute(
        delete(ConceptLink).where(
            ConceptLink.user_id == int(user_id),
            ConceptLink.target_type == "material",
            ConceptLink.target_id == int(material_id),
        )
    )
    if remove_chapter_links:
        chapter_ids = list((
            await db.execute(
                select(Chapter.id)
                .join(Material, Material.id == Chapter.material_id)
                .where(Chapter.material_id == int(material_id), Material.user_id == int(user_id))
            )
        ).scalars().all())
        if chapter_ids:
            await db.execute(
                delete(ConceptLink).where(
                    ConceptLink.user_id == int(user_id), ConceptLink.target_type == "chapter",
                    ConceptLink.target_id.in_(chapter_ids),
                )
            )
    await db.flush()
    removed_edges = 0
    for edge_id in sorted(edge_ids):
        edge = await db.scalar(
            select(ConceptEdge).where(ConceptEdge.id == edge_id, ConceptEdge.user_id == int(user_id))
        )
        if edge is None or edge.source != "material_extract":
            continue
        remaining = await db.scalar(
            select(ConceptSourceEvidence.id).where(ConceptSourceEvidence.edge_id == edge_id).limit(1)
        )
        if remaining is None:
            await db.delete(edge)
            removed_edges += 1

    removed_concepts = 0
    for concept_id in sorted(concept_ids):
        concept = await db.scalar(
            select(Concept).where(Concept.id == concept_id, Concept.user_id == int(user_id))
        )
        if concept is None or concept.source != "material_extract" or concept.review_status != "pending":
            continue
        has_source = await db.scalar(
            select(ConceptSourceEvidence.id).where(ConceptSourceEvidence.concept_id == concept_id).limit(1)
        )
        has_links = await db.scalar(select(ConceptLink.id).where(ConceptLink.concept_id == concept_id).limit(1))
        has_learning = await db.scalar(
            select(LearnerEvidence.id).where(LearnerEvidence.concept_id == concept_id).limit(1)
        )
        has_wrong_question = await db.scalar(
            select(WrongQuestion.id).where(WrongQuestion.concept_id == concept_id).limit(1)
        )
        if has_source is None and has_links is None and has_learning is None and has_wrong_question is None:
            state = await db.scalar(
                select(UserConceptState).where(
                    UserConceptState.user_id == int(user_id), UserConceptState.concept_id == concept_id,
                )
            )
            if state is not None:
                await db.delete(state)
                await db.flush()
            await db.delete(concept)
            removed_concepts += 1
    await db.flush()
    return {"removed_evidence": len(evidence), "removed_edges": removed_edges, "removed_concepts": removed_concepts}


async def sync_material_concepts(db: AsyncSession, user_id: int, material: Material) -> dict[str, Any]:
    """Extract bounded local candidates without any model call or network access."""
    if int(material.user_id) != int(user_id):
        raise LookupError("资料不存在")
    version = await _source_version(db, user_id, int(material.id))
    source_rows = list((
        await db.execute(
            select(ConceptSourceEvidence).where(
                ConceptSourceEvidence.user_id == int(user_id),
                ConceptSourceEvidence.source_type == "material",
                ConceptSourceEvidence.source_id == int(material.id),
            )
        )
    ).scalars().all())
    if source_rows and all(int(row.source_version) == version for row in source_rows):
        return {"material_id": int(material.id), "source_version": version, "created_concepts": 0, "status": "unchanged"}
    if source_rows:
        await forget_material_concepts(db, user_id, int(material.id))

    candidates, aliases, relations = _extract_candidates(str(material.content or ""))
    by_name: dict[str, Concept] = {}
    for name, excerpt in candidates:
        concept = await upsert_concept(
            db, user_id, name, source="material_extract", review_status="pending",
        )
        if concept is None:
            continue
        by_name[normalize_concept_name(name)] = concept
        await link_concept(db, user_id, int(concept.id), "material", int(material.id))
        await record_concept_source_evidence(
            db, user_id, int(concept.id), source_type="material", source_id=int(material.id),
            source_version=version, excerpt=excerpt or name, confidence=0.78,
            review_status=("confirmed" if concept.review_status == "confirmed" else "pending"),
        )

    created_aliases = 0
    for name, alias in aliases:
        concept = by_name.get(normalize_concept_name(name))
        if concept is None:
            continue
        try:
            result = await add_concept_alias(
                db, user_id, int(concept.id), alias, source="material_extract", audit=False,
            )
            created_aliases += int(bool(result.get("created")))
        except ValueError:
            continue

    created_edges = 0
    for first, second, excerpt in relations:
        start, end = by_name.get(normalize_concept_name(first)), by_name.get(normalize_concept_name(second))
        if start is None or end is None:
            continue
        if await add_edge(
            db, user_id, int(start.id), int(end.id), "prerequisite_of", confidence=0.72,
            source="material_extract", review_status="pending",
        ):
            created_edges += 1
        edge = await db.scalar(
            select(ConceptEdge).where(
                ConceptEdge.user_id == int(user_id), ConceptEdge.from_concept_id == int(start.id),
                ConceptEdge.to_concept_id == int(end.id), ConceptEdge.edge_type == "prerequisite_of",
            )
        )
        if edge is not None:
            await record_concept_source_evidence(
                db, user_id, int(end.id), source_type="material", source_id=int(material.id),
                edge_id=int(edge.id), source_version=version, excerpt=excerpt, confidence=0.72,
                review_status=("confirmed" if edge.review_status == "confirmed" else "pending"),
            )
    if by_name:
        await _audit(
            db, user_id, int(next(iter(by_name.values())).id), "material_extracted", actor="system",
            payload={"material_id": int(material.id), "source_version": version, "concept_count": len(by_name)},
        )
    return {
        "material_id": int(material.id), "source_version": version, "created_concepts": len(by_name),
        "created_aliases": created_aliases, "created_edges": created_edges,
        "status": "pending_review" if by_name else "empty",
    }


async def get_prerequisite_gaps(
    db: AsyncSession,
    user_id: int,
    concept_id: int,
    *,
    max_depth: int = 3,
    mastery_threshold: float = 70.0,
) -> list[dict[str, Any]]:
    await _owned_concept(db, user_id, concept_id)
    frontier = {int(concept_id)}
    visited = set(frontier)
    gaps: list[dict[str, Any]] = []
    for depth in range(1, max(1, min(5, int(max_depth))) + 1):
        if not frontier:
            break
        rows = (
            await db.execute(
                select(ConceptEdge, Concept, UserConceptState)
                .join(Concept, Concept.id == ConceptEdge.from_concept_id)
                .outerjoin(
                    UserConceptState,
                    (UserConceptState.user_id == int(user_id))
                    & (UserConceptState.concept_id == ConceptEdge.from_concept_id),
                )
                .where(
                    ConceptEdge.user_id == int(user_id), ConceptEdge.edge_type == "prerequisite_of",
                    ConceptEdge.review_status == "confirmed", ConceptEdge.to_concept_id.in_(frontier),
                    Concept.user_id == int(user_id), Concept.review_status == "confirmed",
                )
            )
        ).all()
        next_frontier: set[int] = set()
        for edge, concept, state in rows:
            if int(concept.id) in visited:
                continue
            visited.add(int(concept.id))
            next_frontier.add(int(concept.id))
            mastery = float(state.mastery_estimate) if state is not None else 0.0
            confidence = float(state.confidence) if state is not None else 0.0
            if mastery < float(mastery_threshold) or confidence < 0.45:
                gaps.append({
                    "concept_id": int(concept.id), "name": concept.name,
                    "mastery_estimate": round(mastery, 2), "confidence": round(confidence, 4),
                    "forgetting_risk": round(float(state.forgetting_risk), 4) if state is not None else 0.85,
                    "depth": depth, "blocks_concept_id": int(edge.to_concept_id),
                    "reason": f"先修概念“{concept.name}”掌握度 {mastery:.0f}%，尚不足以支撑当前学习。",
                })
        frontier = next_frontier
    return sorted(gaps, key=lambda item: (item["depth"], item["mastery_estimate"], item["concept_id"]))


async def get_concept_detail(db: AsyncSession, user_id: int, concept_id: int) -> dict[str, Any]:
    concept = await _owned_concept(db, user_id, concept_id)
    aliases = (
        await db.execute(
            select(ConceptAlias).where(
                ConceptAlias.user_id == int(user_id), ConceptAlias.concept_id == int(concept.id),
            ).order_by(ConceptAlias.id.asc())
        )
    ).scalars().all()
    source_evidence = (
        await db.execute(
            select(ConceptSourceEvidence).where(
                ConceptSourceEvidence.user_id == int(user_id), ConceptSourceEvidence.concept_id == int(concept.id),
            ).order_by(ConceptSourceEvidence.created_at.desc(), ConceptSourceEvidence.id.desc()).limit(100)
        )
    ).scalars().all()
    neighborhood = await get_concept_neighborhood(db, user_id, int(concept.id), depth=1)
    return {
        "id": int(concept.id), "name": concept.name, "description": concept.description,
        "source": concept.source, "review_status": concept.review_status,
        "aliases": [{"id": int(row.id), "alias": row.alias, "source": row.source} for row in aliases],
        "source_evidence": [
            {
                "id": int(row.id), "edge_id": row.edge_id, "source_type": row.source_type,
                "source_id": int(row.source_id), "source_version": int(row.source_version),
                "excerpt": row.excerpt, "confidence": float(row.confidence),
                "review_status": row.review_status,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in source_evidence
        ],
        "neighborhood": neighborhood,
        "prerequisite_gaps": await get_prerequisite_gaps(db, user_id, int(concept.id)),
    }


async def review_concept(
    db: AsyncSession,
    user_id: int,
    concept_id: int,
    review_status: str,
) -> dict[str, Any]:
    if review_status not in {"confirmed", "rejected"}:
        raise ValueError("review_status 必须为 confirmed 或 rejected")
    concept = await _owned_concept(db, user_id, concept_id)
    previous = concept.review_status
    concept.review_status = review_status
    rows = (
        await db.execute(
            select(ConceptSourceEvidence).where(
                ConceptSourceEvidence.user_id == int(user_id), ConceptSourceEvidence.concept_id == int(concept.id),
            )
        )
    ).scalars().all()
    for row in rows:
        if row.edge_id is None:
            row.review_status = review_status

    incident = (
        await db.execute(
            select(ConceptEdge).where(
                ConceptEdge.user_id == int(user_id),
                or_(ConceptEdge.from_concept_id == int(concept.id), ConceptEdge.to_concept_id == int(concept.id)),
            )
        )
    ).scalars().all()
    for edge in incident:
        if review_status == "rejected":
            edge.review_status = "rejected"
        else:
            endpoints = (
                await db.execute(
                    select(Concept.review_status).where(
                        Concept.user_id == int(user_id),
                        Concept.id.in_([int(edge.from_concept_id), int(edge.to_concept_id)]),
                    )
                )
            ).scalars().all()
            if len(endpoints) == 2 and all(status == "confirmed" for status in endpoints):
                edge.review_status = "confirmed"
        edge_evidence = (
            await db.execute(select(ConceptSourceEvidence).where(ConceptSourceEvidence.edge_id == int(edge.id)))
        ).scalars().all()
        for evidence in edge_evidence:
            evidence.review_status = edge.review_status
    await _audit(
        db, user_id, int(concept.id), "reviewed",
        payload={"previous_status": previous, "review_status": review_status},
    )
    return await get_concept_detail(db, user_id, int(concept.id))


async def create_concept_relation(
    db: AsyncSession,
    user_id: int,
    from_concept_id: int,
    to_concept_id: int,
    edge_type: str,
    *,
    confidence: float = 1.0,
) -> dict[str, Any]:
    await _owned_concept(db, user_id, from_concept_id)
    await _owned_concept(db, user_id, to_concept_id)
    created = await add_edge(
        db, user_id, from_concept_id, to_concept_id, edge_type,
        confidence=confidence, source="manual", review_status="confirmed",
    )
    if not created:
        raise ValueError("关系已存在、类型无效，或者会造成先修循环")
    canonical_type = "prerequisite_of" if edge_type == "prerequisite" else edge_type
    edge = await db.scalar(
        select(ConceptEdge).where(
            ConceptEdge.user_id == int(user_id), ConceptEdge.from_concept_id == int(from_concept_id),
            ConceptEdge.to_concept_id == int(to_concept_id), ConceptEdge.edge_type == canonical_type,
        )
    )
    await _audit(
        db, user_id, int(to_concept_id), "relation_added",
        payload={"edge_id": int(edge.id), "from_concept_id": int(from_concept_id), "edge_type": canonical_type},
    )
    return {
        "id": int(edge.id), "from_concept_id": int(from_concept_id), "to_concept_id": int(to_concept_id),
        "edge_type": canonical_type, "confidence": float(edge.confidence), "review_status": edge.review_status,
    }


async def review_concept_relation(
    db: AsyncSession,
    user_id: int,
    edge_id: int,
    review_status: str,
) -> dict[str, Any]:
    if review_status not in {"confirmed", "rejected"}:
        raise ValueError("review_status 必须为 confirmed 或 rejected")
    edge = await db.scalar(select(ConceptEdge).where(ConceptEdge.id == int(edge_id), ConceptEdge.user_id == int(user_id)))
    if edge is None:
        raise LookupError("概念关系不存在")
    if review_status == "confirmed":
        pending = await db.scalar(
            select(Concept.id).where(
                Concept.user_id == int(user_id),
                Concept.id.in_([int(edge.from_concept_id), int(edge.to_concept_id)]),
                Concept.review_status != "confirmed",
            )
        )
        if pending is not None:
            raise ValueError("确认关系前需要先确认两端概念")
    edge.review_status = review_status
    source_rows = (
        await db.execute(select(ConceptSourceEvidence).where(ConceptSourceEvidence.edge_id == int(edge.id)))
    ).scalars().all()
    for row in source_rows:
        row.review_status = review_status
    await _audit(
        db, user_id, int(edge.to_concept_id), "relation_reviewed",
        payload={"edge_id": int(edge.id), "review_status": review_status},
    )
    return {"id": int(edge.id), "review_status": edge.review_status}


async def merge_concepts(
    db: AsyncSession,
    user_id: int,
    target_concept_id: int,
    source_concept_id: int,
) -> dict[str, Any]:
    target = await _owned_concept(db, user_id, target_concept_id)
    source = await _owned_concept(db, user_id, source_concept_id)
    if int(target.id) == int(source.id):
        raise ValueError("不能将概念与自身合并")
    source_name = source.name
    target_id, source_id = int(target.id), int(source.id)
    migrated = {"aliases": 0, "links": 0, "edges": 0, "source_evidence": 0, "learner_evidence": 0, "wrong_questions": 0}

    aliases = list((
        await db.execute(select(ConceptAlias).where(ConceptAlias.user_id == int(user_id), ConceptAlias.concept_id == source_id))
    ).scalars().all())
    for row in aliases:
        if row.alias_normalized == target.name_normalized:
            await db.delete(row)
        else:
            row.concept_id = target_id
            migrated["aliases"] += 1
    await db.flush()

    links = list((
        await db.execute(select(ConceptLink).where(ConceptLink.user_id == int(user_id), ConceptLink.concept_id == source_id))
    ).scalars().all())
    for row in links:
        duplicate = await db.scalar(
            select(ConceptLink.id).where(
                ConceptLink.user_id == int(user_id), ConceptLink.concept_id == target_id,
                ConceptLink.target_type == row.target_type, ConceptLink.target_id == row.target_id,
            )
        )
        if duplicate is not None:
            await db.delete(row)
        else:
            row.concept_id = target_id
            migrated["links"] += 1
        await db.flush()

    edges = list((
        await db.execute(
            select(ConceptEdge).where(
                ConceptEdge.user_id == int(user_id),
                or_(ConceptEdge.from_concept_id == source_id, ConceptEdge.to_concept_id == source_id),
            )
        )
    ).scalars().all())
    for edge in edges:
        start = target_id if int(edge.from_concept_id) == source_id else int(edge.from_concept_id)
        end = target_id if int(edge.to_concept_id) == source_id else int(edge.to_concept_id)
        if start == end:
            await db.delete(edge)
            await db.flush()
            continue
        duplicate = await db.scalar(
            select(ConceptEdge).where(
                ConceptEdge.user_id == int(user_id), ConceptEdge.id != int(edge.id),
                ConceptEdge.from_concept_id == start, ConceptEdge.to_concept_id == end,
                ConceptEdge.edge_type == edge.edge_type,
            )
        )
        if duplicate is not None:
            supporting_rows = (
                await db.execute(select(ConceptSourceEvidence).where(ConceptSourceEvidence.edge_id == int(edge.id)))
            ).scalars().all()
            for supporting in supporting_rows:
                supporting.edge_id = int(duplicate.id)
            await db.delete(edge)
        else:
            edge.from_concept_id, edge.to_concept_id = start, end
            migrated["edges"] += 1
        await db.flush()

    provenance = (
        await db.execute(
            select(ConceptSourceEvidence).where(
                ConceptSourceEvidence.user_id == int(user_id), ConceptSourceEvidence.concept_id == source_id,
            )
        )
    ).scalars().all()
    for row in provenance:
        row.concept_id = target_id
        migrated["source_evidence"] += 1

    evidence_rows = list((
        await db.execute(
            select(LearnerEvidence).where(LearnerEvidence.user_id == int(user_id), LearnerEvidence.concept_id == source_id)
        )
    ).scalars().all())
    for row in evidence_rows:
        duplicate = None
        if row.source_event_id is not None:
            duplicate = await db.scalar(
                select(LearnerEvidence.id).where(
                    LearnerEvidence.user_id == int(user_id), LearnerEvidence.concept_id == target_id,
                    LearnerEvidence.evidence_type == row.evidence_type,
                    LearnerEvidence.source_event_id == row.source_event_id,
                )
            )
        if duplicate is None:
            row.concept_id = target_id
            migrated["learner_evidence"] += 1
        else:
            await db.delete(row)
        await db.flush()

    wrong_rows = (
        await db.execute(select(WrongQuestion).where(WrongQuestion.user_id == int(user_id), WrongQuestion.concept_id == source_id))
    ).scalars().all()
    for row in wrong_rows:
        row.concept_id = target_id
        migrated["wrong_questions"] += 1
    outbox_rows = (
        await db.execute(
            select(ProjectionOutbox).where(ProjectionOutbox.user_id == int(user_id), ProjectionOutbox.concept_id == source_id)
        )
    ).scalars().all()
    for row in outbox_rows:
        row.concept_id = target_id
    source_audits = (
        await db.execute(
            select(ConceptAuditEvent).where(
                ConceptAuditEvent.user_id == int(user_id), ConceptAuditEvent.concept_id == source_id,
            )
        )
    ).scalars().all()
    for row in source_audits:
        row.concept_id = target_id
    source_state = await db.scalar(
        select(UserConceptState).where(UserConceptState.user_id == int(user_id), UserConceptState.concept_id == source_id)
    )
    if source_state is not None:
        await db.delete(source_state)
        await db.flush()
    await db.delete(source)
    await db.flush()
    await add_concept_alias(db, user_id, target_id, source_name, source="merge", audit=False)
    await recompute_concept_state(db, user_id, target_id)
    await _audit(
        db, user_id, target_id, "merged",
        payload={"source_concept_id": source_id, "source_name": source_name, "migrated": migrated},
    )
    detail = await get_concept_detail(db, user_id, target_id)
    detail["merge"] = {"source_concept_id": source_id, "migrated": migrated}
    return detail


async def split_concept(
    db: AsyncSession,
    user_id: int,
    concept_id: int,
    *,
    name: str,
    alias_ids: list[int] | None = None,
    source_evidence_ids: list[int] | None = None,
    link_ids: list[int] | None = None,
) -> dict[str, Any]:
    source = await _owned_concept(db, user_id, concept_id)
    existing = await db.scalar(
        select(Concept.id).where(
            Concept.user_id == int(user_id), Concept.name_normalized == normalize_concept_name(name),
        )
    )
    if existing is not None:
        raise ValueError("拆分后的概念名称已存在")
    target = await upsert_concept(db, user_id, name, source="manual", review_status="confirmed")
    if target is None:
        raise ValueError("拆分后的概念名称无效")
    moved = {"aliases": 0, "source_evidence": 0, "links": 0}
    for model, identifiers, key in (
        (ConceptAlias, alias_ids or [], "aliases"),
        (ConceptSourceEvidence, source_evidence_ids or [], "source_evidence"),
        (ConceptLink, link_ids or [], "links"),
    ):
        for row_id in set(int(value) for value in identifiers):
            row = await db.scalar(
                select(model).where(model.id == row_id, model.user_id == int(user_id), model.concept_id == int(source.id))
            )
            if row is None:
                raise ValueError(f"无法迁移不属于原概念的记录: {row_id}")
            row.concept_id = int(target.id)
            if isinstance(row, ConceptSourceEvidence) and row.edge_id is not None:
                row.edge_id = None
            moved[key] += 1
    await db.flush()
    await _audit(
        db, user_id, int(source.id), "split",
        payload={"new_concept_id": int(target.id), "new_name": target.name, "moved": moved},
    )
    await _audit(
        db, user_id, int(target.id), "split_created",
        payload={"source_concept_id": int(source.id), "moved": moved},
    )
    detail = await get_concept_detail(db, user_id, int(target.id))
    detail["split"] = {"source_concept_id": int(source.id), "moved": moved}
    return detail


async def delete_concept(db: AsyncSession, user_id: int, concept_id: int) -> dict[str, Any]:
    concept = await _owned_concept(db, user_id, concept_id)
    identifier, name = int(concept.id), concept.name
    wrong_rows = (
        await db.execute(
            select(WrongQuestion).where(WrongQuestion.user_id == int(user_id), WrongQuestion.concept_id == identifier)
        )
    ).scalars().all()
    for row in wrong_rows:
        row.concept_id = None
    await _audit(db, user_id, None, "deleted", payload={"concept_id": identifier, "name": name})
    await db.delete(concept)
    await db.flush()
    return {"deleted": True, "concept_id": identifier, "name": name}


async def list_concept_audit(
    db: AsyncSession, user_id: int, concept_id: int, *, limit: int = 50,
) -> list[dict[str, Any]]:
    await _owned_concept(db, user_id, concept_id)
    rows = (
        await db.execute(
            select(ConceptAuditEvent).where(
                ConceptAuditEvent.user_id == int(user_id), ConceptAuditEvent.concept_id == int(concept_id),
            ).order_by(ConceptAuditEvent.id.desc()).limit(max(1, min(200, int(limit))))
        )
    ).scalars().all()
    return [
        {
            "id": int(row.id), "operation": row.operation, "actor": row.actor,
            "payload": row.payload or {}, "created_at": row.created_at.isoformat() if row.created_at else None,
        }
        for row in rows
    ]
