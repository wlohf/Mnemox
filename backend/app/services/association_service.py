"""联想引擎 v1（决策 D2 应用层）：学新内容时自动关联旧知识。

触发方式：对新文本做**概念名匹配**（零 LLM 成本、确定性），命中已有概念后
沿图收集证据（旧笔记、错题、先修关系）。价值门槛：没有证据的联想宁可不发。
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.concept import Concept, ConceptEdge, ConceptLink
from app.models.learner_model import UserConceptState
from app.models.note import Note
from app.models.question import WrongQuestion
from app.services.concept_service import link_concept

logger = logging.getLogger(__name__)

MAX_ASSOCIATIONS = 3
MAX_EVIDENCE_PER_CONCEPT = 3
_MIN_MATCH_NAME_LENGTH = 2


async def match_concepts_in_text(db: AsyncSession, user_id: int, text: str) -> list[Concept]:
    """在文本中匹配当前用户已有的概念名（大小写不敏感）。"""
    haystack = str(text or "").lower()
    if not haystack.strip():
        return []
    result = await db.execute(select(Concept).where(Concept.user_id == user_id))
    matched = []
    for concept in result.scalars().all():
        needle = str(concept.name_normalized or "")
        if len(needle) >= _MIN_MATCH_NAME_LENGTH and needle in haystack:
            matched.append(concept)
    return matched


async def attach_note_to_concepts(db: AsyncSession, user_id: int, note: Note) -> list[Concept]:
    """笔记保存时挂图：内容中出现的概念建立 note EXPLAINS concept 挂接。"""
    await detach_note_from_concepts(db, user_id, int(note.id), link_type="explains")
    matched = await match_concepts_in_text(
        db, user_id, f"{note.title or ''}\n{note.content or ''}"
    )
    for concept in matched:
        await link_concept(db, user_id, concept.id, "note", int(note.id), link_type="explains")
    return matched


async def detach_note_from_concepts(
    db: AsyncSession,
    user_id: int,
    note_id: int,
    *,
    link_type: str | None = None,
) -> int:
    """Remove graph links for a note before it is re-matched or deleted."""
    clauses = [
        ConceptLink.user_id == int(user_id),
        ConceptLink.target_type == "note",
        ConceptLink.target_id == int(note_id),
    ]
    if link_type is not None:
        clauses.append(ConceptLink.link_type == str(link_type))
    result = await db.execute(delete(ConceptLink).where(*clauses))
    return int(result.rowcount or 0)


async def _collect_evidence(
    db: AsyncSession,
    user_id: int,
    concept_ids: list[int],
    *,
    exclude_note_id: int | None = None,
) -> dict[int, dict[str, list[dict[str, Any]]]]:
    """按概念收集挂接证据：旧笔记与错题。"""
    if not concept_ids:
        return {}
    link_result = await db.execute(
        select(ConceptLink).where(
            ConceptLink.user_id == user_id,
            ConceptLink.concept_id.in_(concept_ids),
            ConceptLink.target_type.in_(("note", "wrong_question")),
        )
    )
    note_ids: set[int] = set()
    wrong_ids: set[int] = set()
    links_by_concept: dict[int, list[ConceptLink]] = {}
    for link in link_result.scalars().all():
        if link.target_type == "note" and link.target_id == exclude_note_id:
            continue
        links_by_concept.setdefault(link.concept_id, []).append(link)
        if link.target_type == "note":
            note_ids.add(link.target_id)
        else:
            wrong_ids.add(link.target_id)

    notes: dict[int, Note] = {}
    if note_ids:
        note_result = await db.execute(
            select(Note).where(Note.user_id == user_id, Note.id.in_(note_ids))
        )
        notes = {int(n.id): n for n in note_result.scalars().all()}
    wrongs: dict[int, WrongQuestion] = {}
    if wrong_ids:
        wrong_result = await db.execute(
            select(WrongQuestion).where(WrongQuestion.user_id == user_id, WrongQuestion.id.in_(wrong_ids))
        )
        wrongs = {int(w.id): w for w in wrong_result.scalars().all()}

    evidence: dict[int, dict[str, list[dict[str, Any]]]] = {}
    for concept_id, links in links_by_concept.items():
        bucket = {"notes": [], "wrong_questions": []}
        for link in links:
            if link.target_type == "note":
                note = notes.get(link.target_id)
                if note and len(bucket["notes"]) < MAX_EVIDENCE_PER_CONCEPT:
                    bucket["notes"].append(
                        {
                            "id": int(note.id),
                            "title": str(note.title or "未命名笔记"),
                            "updated_at": note.updated_at.isoformat() if note.updated_at else None,
                            "route": "/notes",
                        }
                    )
            else:
                wrong = wrongs.get(link.target_id)
                if wrong and len(bucket["wrong_questions"]) < MAX_EVIDENCE_PER_CONCEPT:
                    bucket["wrong_questions"].append(
                        {
                            "id": int(wrong.id),
                            "knowledge_point": wrong.knowledge_point,
                            "mastery_status": wrong.mastery_status,
                            "wrong_count": int(wrong.wrong_count or 0),
                            "route": "/wrong-questions",
                        }
                    )
        evidence[concept_id] = bucket
    return evidence


async def find_associations(
    db: AsyncSession,
    user_id: int,
    text: str,
    *,
    limit: int = MAX_ASSOCIATIONS,
    exclude_note_id: int | None = None,
) -> list[dict[str, Any]]:
    """对一段新内容产生"旧知识联想"。

    价值门槛：概念必须带有证据（旧笔记/错题）或先修关系，否则不返回
    （低价值联想宁可不发，避免打扰）。返回按证据强度排序。
    """
    matched = await match_concepts_in_text(db, user_id, text)
    if not matched:
        return []
    matched_ids = [c.id for c in matched]

    # 1 跳邻居（重点关注指向匹配概念的先修边）
    edge_result = await db.execute(
        select(ConceptEdge).where(
            ConceptEdge.user_id == user_id,
            (ConceptEdge.from_concept_id.in_(matched_ids))
            | (ConceptEdge.to_concept_id.in_(matched_ids)),
        )
    )
    edges = list(edge_result.scalars().all())
    neighbor_ids = {e.from_concept_id for e in edges} | {e.to_concept_id for e in edges}
    all_ids = list(set(matched_ids) | neighbor_ids)

    evidence = await _collect_evidence(db, user_id, all_ids, exclude_note_id=exclude_note_id)

    state_result = await db.execute(
        select(UserConceptState).where(
            UserConceptState.user_id == user_id,
            UserConceptState.concept_id.in_(all_ids),
        )
    )
    states = {int(state.concept_id): state for state in state_result.scalars().all()}

    neighbor_names: dict[int, str] = {}
    if neighbor_ids:
        neighbor_result = await db.execute(
            select(Concept).where(Concept.user_id == user_id, Concept.id.in_(neighbor_ids))
        )
        neighbor_names = {int(c.id): c.name for c in neighbor_result.scalars().all()}

    associations: list[dict[str, Any]] = []
    for concept in matched:
        concept_state = states.get(int(concept.id))
        bucket = evidence.get(concept.id, {"notes": [], "wrong_questions": []})
        prerequisites = [
            {
                "concept_id": e.from_concept_id,
                "name": neighbor_names.get(e.from_concept_id, ""),
                "evidence": evidence.get(e.from_concept_id, {"notes": [], "wrong_questions": []}),
            }
            for e in edges
            if e.edge_type == "prerequisite_of" and e.to_concept_id == concept.id
        ]
        related = [
            {
                "concept_id": other_id,
                "name": neighbor_names.get(other_id, ""),
            }
            for e in edges
            if e.edge_type == "related_to"
            for other_id in ((e.from_concept_id, e.to_concept_id))
            if other_id != concept.id and other_id in neighbor_ids
        ]

        evidence_count = len(bucket["notes"]) + len(bucket["wrong_questions"]) + sum(
            len(p["evidence"]["notes"]) + len(p["evidence"]["wrong_questions"]) for p in prerequisites
        )
        # 价值门槛：必须有证据或先修关系
        if evidence_count == 0 and not prerequisites:
            continue

        reason_parts = []
        if bucket["wrong_questions"]:
            reason_parts.append(f"你在这个知识点上有 {len(bucket['wrong_questions'])} 条错题记录")
        if bucket["notes"]:
            reason_parts.append(f"你写过 {len(bucket['notes'])} 条相关笔记")
        if prerequisites:
            prereq_names = "、".join(p["name"] for p in prerequisites if p["name"])
            if prereq_names:
                reason_parts.append(f"它的先修知识是「{prereq_names}」")

        associations.append(
            {
                "concept_id": concept.id,
                "concept_name": concept.name,
                "mastery": (
                    float(concept_state.mastery_estimate)
                    if concept_state is not None
                    else float(concept.mastery or 0.0)
                ),
                "mastery_source": (
                    "user_concept_state" if concept_state is not None else "legacy_compatibility"
                ),
                "reason": "；".join(reason_parts),
                "score": evidence_count * 2 + len(prerequisites),
                "evidence": bucket,
                "prerequisites": prerequisites,
                "related_concepts": related[:5],
            }
        )

    associations.sort(key=lambda item: item["score"], reverse=True)
    return associations[: max(1, min(int(limit or MAX_ASSOCIATIONS), 10))]
