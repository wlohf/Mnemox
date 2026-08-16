"""Coach attribution for explicit knowledge-association requests."""
from __future__ import annotations

import hashlib
import re
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.coach import CoachNudge
from app.services.coach_action_service import coach_nudge_to_dict, create_coach_nudge
from app.services.coach_event_service import record_coach_event
from app.services.coach_skills.base import CoachSkillResult

ASSOCIATION_RECALL_EVENT_TYPE = "association.recalled"
ASSOCIATION_RECALL_SKILL_ID = "association_recall"


def _normalized_query(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip()).lower()


def _query_hash(text: str) -> str:
    return hashlib.sha256(_normalized_query(text).encode("utf-8")).hexdigest()[:32]


def _request_fingerprint(user_id: int, query_text: str, association_ids: list[int]) -> tuple[str, str]:
    sorted_ids = sorted(set(association_ids))
    bucket = int(datetime.now().timestamp() // (6 * 60 * 60))
    raw = f"{int(user_id)}:{_query_hash(query_text)}:{','.join(str(item) for item in sorted_ids)}:{bucket}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32], ",".join(str(item) for item in sorted_ids)


def _iter_evidence(association: dict[str, Any]):
    evidence = association.get("evidence") or {}
    for source in evidence.get("notes") or []:
        yield "note", source
    for source in evidence.get("wrong_questions") or []:
        yield "wrong_question", source
    for prerequisite in association.get("prerequisites") or []:
        prerequisite_evidence = prerequisite.get("evidence") or {}
        for source in prerequisite_evidence.get("notes") or []:
            yield "note", source
        for source in prerequisite_evidence.get("wrong_questions") or []:
            yield "wrong_question", source


def _sources_from_associations(associations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sources: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for association in associations:
        for source_type, source in _iter_evidence(association):
            source_id = str(source.get("id") or "")
            key = (source_type, source_id)
            if key in seen:
                continue
            seen.add(key)
            sources.append(
                {
                    "type": source_type,
                    "id": source.get("id"),
                    "title": source.get("title") or source.get("knowledge_point"),
                    "route": source.get("route"),
                    "category": "association_evidence",
                }
            )
    return sources


async def create_association_recall_nudge(
    db: AsyncSession,
    user_id: int,
    *,
    query_text: str,
    associations: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Create a traceable, confirmation-first nudge for a non-empty recall result.

    The Coach event is deduplicated for six hours by normalized query and matched
    concept IDs. The nudge is then reused for the existing event, so repeated
    explicit requests do not inflate Coach attribution metrics.
    """

    if not associations:
        return None

    association_ids = sorted(
        {int(item["concept_id"]) for item in associations if item.get("concept_id") is not None}
    )
    query_hash = _query_hash(query_text)
    fingerprint, association_id_text = _request_fingerprint(user_id, query_text, association_ids)
    dedupe_key = f"association.recall:{fingerprint}:{association_id_text}"
    event = await record_coach_event(
        db,
        user_id,
        ASSOCIATION_RECALL_EVENT_TYPE,
        "concepts",
        {
            "source": "concepts.associate",
            "query_hash": query_hash,
            "association_ids": association_ids,
            "association_count": len(association_ids),
        },
        dedupe_key=dedupe_key,
        event_id=f"ce_ar_{fingerprint}",
    )

    existing_result = await db.execute(
        select(CoachNudge)
        .where(
            CoachNudge.user_id == int(user_id),
            CoachNudge.event_id == event["id"],
            CoachNudge.skill_id == ASSOCIATION_RECALL_SKILL_ID,
        )
        .order_by(CoachNudge.created_at.asc())
        .limit(1)
    )
    existing = existing_result.scalar_one_or_none()
    if existing is not None:
        return {"event": event, "nudge": coach_nudge_to_dict(existing)}

    names = [str(item.get("concept_name") or "相关知识") for item in associations[:3]]
    name_text = "、".join(names)
    first_reason = str(associations[0].get("reason") or "已有相关知识证据")
    sources = _sources_from_associations(associations)
    result = CoachSkillResult(
        title=f"发现「{name_text}」的旧知识关联",
        body=f"这段内容和你已有知识有明确关联。{first_reason}。先查看依据，再决定是否补充复习。",
        suggested_action={
            "type": "view_associations",
            "label": "查看关联",
            "route": "/agent",
            "association_ids": association_ids,
        },
        route="/agent",
        requires_confirmation=False,
        explainability={
            "reason": "联想引擎根据概念匹配、先修关系和历史证据生成了结果",
            "source": {
                "type": "association_engine",
                "endpoint": "/api/concepts/associate",
                "event_id": event["id"],
            },
            "association_ids": association_ids,
            "associations": associations,
            "sources": sources,
            "query_hash": query_hash,
        },
    )
    nudge_id = f"cn_ar_{event['id'].removeprefix('ce_ar_')}"
    try:
        async with db.begin_nested():
            nudge = await create_coach_nudge(
                db,
                user_id,
                event_id=event["id"],
                skill_id=ASSOCIATION_RECALL_SKILL_ID,
                policy={
                    "channel": "agent_panel",
                    "priority": "medium",
                    "reason": "explicit_association_request",
                    "evidence": [
                        f"匹配到 {len(association_ids)} 个已有概念",
                        f"找到 {len(sources)} 条可追溯证据",
                    ],
                },
                result=result,
                nudge_id=nudge_id,
            )
    except IntegrityError:
        existing = await db.scalar(
            select(CoachNudge).where(
                CoachNudge.id == nudge_id,
                CoachNudge.user_id == int(user_id),
            )
        )
        if existing is None:
            raise
        nudge = coach_nudge_to_dict(existing)
    return {"event": event, "nudge": nudge}
