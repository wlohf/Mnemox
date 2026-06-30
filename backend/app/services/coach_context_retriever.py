"""Composite context retrieval for coach skills.

Phase 3 starts deliberately small: retrieve only user-scoped notes and memories,
return explicit source indicators, and wrap retrieved text as untrusted context.
"""
from __future__ import annotations

import re
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.memory import UserMemory
from app.models.note import Note
from app.utils.prompt_safety import wrap_untrusted_context

CONFIRMED_REVIEW_STATUS = "confirmed"

def _terms_from_text(value: Any) -> list[str]:
    text = str(value or "").strip().lower()
    if not text:
        return []
    raw_terms = re.findall(r"[\w\u4e00-\u9fff]{2,}", text)
    stop = {
        "我",
        "我们",
        "这个",
        "那个",
        "今天",
        "现在",
        "学习",
        "任务",
        "复习",
        "the",
        "and",
        "that",
        "this",
    }
    terms: list[str] = []

    def add_term(term: str) -> None:
        if term in stop or term in terms:
            return
        terms.append(term[:40])

    for term in raw_terms:
        add_term(term)
        if re.search(r"[\u4e00-\u9fff]", term) and len(term) > 4:
            # Chinese text often arrives as one long token. Add stable short
            # windows so "线性代数任务太多了" can still match notes/memories
            # containing "线性代数".
            for size in (4, 3, 2):
                for idx in range(0, len(term) - size + 1):
                    add_term(term[idx : idx + size])
    return terms[:8]


def _query_terms(event: dict[str, Any], snapshot: dict[str, Any]) -> list[str]:
    payload = event.get("payload") or {}
    values: list[Any] = [
        payload.get("text"),
        payload.get("message"),
        payload.get("task_name"),
        event.get("event_type"),
    ]
    tasks = snapshot.get("tasks") or {}
    for item in (tasks.get("today_tasks") or [])[:2]:
        values.append(item.get("title"))
    for item in (tasks.get("overdue_tasks") or [])[:2]:
        values.append(item.get("title"))
    for item in ((snapshot.get("review") or {}).get("due_review_items") or [])[:2]:
        values.append(item.get("title"))
        values.append(item.get("knowledge_point"))

    terms: list[str] = []
    for value in values:
        for term in _terms_from_text(value):
            if term not in terms:
                terms.append(term)
    return terms[:10]


def _score_text(terms: list[str], *values: Any) -> int:
    text = "\n".join(str(v or "").lower() for v in values)
    return sum(1 for term in terms if term and term.lower() in text)


def _compact(value: Any, limit: int = 240) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[:limit]


async def retrieve_coach_context(
    db: AsyncSession,
    user_id: int,
    event: dict[str, Any],
    snapshot: dict[str, Any],
    *,
    max_notes: int = 3,
    max_memories: int = 3,
) -> dict[str, Any]:
    terms = _query_terms(event, snapshot)
    sources: list[dict[str, Any]] = []
    wrapped_blocks: list[str] = []

    if terms:
        note_filters = []
        memory_filters = []
        for term in terms[:6]:
            like = f"%{term}%"
            note_filters.append(or_(Note.title.ilike(like), Note.content.ilike(like), Note.tags.ilike(like)))
            memory_filters.append(or_(UserMemory.memory_key.ilike(like), UserMemory.memory_value.ilike(like), UserMemory.category.ilike(like)))

        note_result = await db.execute(
            select(Note)
            .where(Note.user_id == user_id, or_(*note_filters))
            .order_by(Note.updated_at.desc(), Note.created_at.desc(), Note.id.desc())
            .limit(max_notes * 4)
        )
        note_candidates = note_result.scalars().all()
        note_candidates.sort(key=lambda n: _score_text(terms, n.title, n.content, n.tags), reverse=True)
        for note in note_candidates[:max_notes]:
            source = {
                "type": "note",
                "id": note.id,
                "title": note.title or "无标题笔记",
                "route": "/notes",
                "snippet": _compact(note.content, 160),
            }
            sources.append(source)
            wrapped_blocks.append(
                wrap_untrusted_context(
                    f"Coach 检索笔记：{source['title']}",
                    f"标题：{note.title or '无标题'}\n标签：{note.tags or '[]'}\n正文：{note.content or ''}",
                    source=f"note:{note.id}",
                    max_chars=1800,
                )
            )

        memory_result = await db.execute(
            select(UserMemory)
            .where(
                UserMemory.user_id == user_id,
                UserMemory.status == "active",
                UserMemory.review_status == CONFIRMED_REVIEW_STATUS,
                or_(*memory_filters),
            )
            .order_by(UserMemory.last_seen_at.desc(), UserMemory.updated_at.desc(), UserMemory.id.desc())
            .limit(max_memories * 4)
        )
        memory_candidates = memory_result.scalars().all()
        memory_candidates.sort(key=lambda m: _score_text(terms, m.memory_key, m.memory_value, m.category), reverse=True)
        for memory in memory_candidates[:max_memories]:
            source = {
                "type": "memory",
                "id": memory.id,
                "title": memory.memory_key,
                "category": memory.category,
                "snippet": _compact(memory.memory_value, 160),
            }
            sources.append(source)
            wrapped_blocks.append(
                wrap_untrusted_context(
                    f"Coach 检索记忆：{memory.memory_key}",
                    f"类别：{memory.category}\n内容：{memory.memory_value}",
                    source=f"memory:{memory.id}",
                    max_chars=1000,
                )
            )

    return {
        "query_terms": terms,
        "sources": sources,
        "wrapped_context": "\n".join(wrapped_blocks),
    }
