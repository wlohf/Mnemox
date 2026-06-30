"""User-scoped note retrieval for goal evidence and agent previews."""
from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.goal import Goal, Task
from app.models.memory import UserMemory
from app.models.note import Note, NoteLink

CONFIRMED_REVIEW_STATUS = "confirmed"

_CJK_RE = re.compile(r"[\u4e00-\u9fff]{2,}")
_WORD_RE = re.compile(r"[A-Za-z0-9_]{2,}")


def _safe_tags(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        value = json.loads(raw)
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()][:8]
    except Exception:
        return []
    return []


def _to_iso(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _tokens(text: str) -> list[str]:
    text = (text or "").strip().lower()
    if not text:
        return []
    tokens: list[str] = []
    tokens.extend(match.group(0) for match in _WORD_RE.finditer(text))
    for match in _CJK_RE.finditer(text):
        chunk = match.group(0)
        tokens.append(chunk)
        tokens.extend(chunk[i : i + 2] for i in range(max(0, len(chunk) - 1)))
    seen: set[str] = set()
    out: list[str] = []
    for token in tokens:
        if token not in seen:
            seen.add(token)
            out.append(token)
    return out[:20]


def _excerpt(content: str | None, terms: list[str], max_chars: int = 240) -> str:
    text = re.sub(r"\s+", " ", (content or "").strip())
    if not text:
        return ""
    lower = text.lower()
    start = 0
    for term in terms:
        idx = lower.find(term.lower())
        if idx >= 0:
            start = max(0, idx - 60)
            break
    snippet = text[start : start + max_chars].strip()
    if start > 0:
        snippet = "..." + snippet
    if start + max_chars < len(text):
        snippet += "..."
    return snippet


def _days_since(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return max(0.0, (datetime.now() - value).total_seconds() / 86400.0)
    return None


class NoteRetriever:
    """Phase-1 SQL and keyword retrieval for notes."""

    @staticmethod
    async def retrieve_notes(
        db: AsyncSession,
        user_id: int,
        query: str,
        goal_id: int | None = None,
        material_id: int | None = None,
        limit: int = 6,
    ) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit or 6), 12))
        terms = _tokens(query)
        goal_material_id = material_id
        goal_text = ""
        task_terms: list[str] = []
        goal_task_ids: set[int] = set()
        goal_task_note_ids: set[int] = set()

        if goal_id is not None:
            goal_result = await db.execute(select(Goal).where(Goal.id == goal_id, Goal.user_id == user_id))
            goal = goal_result.scalar_one_or_none()
            if goal is None:
                return []
            goal_material_id = goal_material_id if goal_material_id is not None else goal.material_id
            goal_text = f"{goal.title or ''} {goal.description or ''}"
            terms = list(dict.fromkeys([*terms, *_tokens(goal_text)]))[:24]
            task_result = await db.execute(
                select(Task.id, Task.title, Task.description)
                .where(Task.goal_id == goal_id)
                .order_by(Task.updated_at.desc(), Task.id.desc())
                .limit(50)
            )
            for task_id, title, description in task_result.all():
                goal_task_ids.add(int(task_id))
                task_terms.extend(_tokens(f"{title or ''} {description or ''}"))
            terms = list(dict.fromkeys([*terms, *task_terms]))[:28]
            if goal_task_ids:
                task_note_result = await db.execute(
                    select(NoteLink.note_id).where(
                        NoteLink.link_type == "task",
                        NoteLink.link_id.in_(goal_task_ids),
                    )
                )
                goal_task_note_ids = {int(note_id) for note_id in task_note_result.scalars().all()}

        stmt = select(Note).options(selectinload(Note.links)).where(Note.user_id == user_id)
        related_filters = []
        if goal_material_id is not None:
            linked_by_material = select(NoteLink.note_id).where(NoteLink.link_type == "material", NoteLink.link_id == goal_material_id)
            stmt = stmt.where(or_(Note.material_id.is_(None), Note.material_id == goal_material_id, Note.id.in_(linked_by_material)))
            related_filters.append(or_(Note.material_id == goal_material_id, Note.id.in_(linked_by_material)))
        if goal_id is not None:
            linked_by_goal = select(NoteLink.note_id).where(NoteLink.link_type == "goal", NoteLink.link_id == goal_id)
            linked_by_task = (
                select(NoteLink.note_id)
                .join(Task, Task.id == NoteLink.link_id)
                .where(NoteLink.link_type == "task", Task.goal_id == goal_id)
            )
            related_filters.append(or_(Note.id.in_(linked_by_goal), Note.id.in_(linked_by_task)))
        if terms:
            term_filters = []
            for term in terms[:8]:
                like = f"%{term}%"
                term_filters.append(or_(Note.title.ilike(like), Note.content.ilike(like), Note.tags.ilike(like)))
            related_filters.append(or_(*term_filters))
        if related_filters:
            stmt = stmt.where(or_(*related_filters))

        result = await db.execute(stmt.order_by(Note.updated_at.desc(), Note.id.desc()).limit(max(limit * 5, 20)))
        notes = list(result.scalars().unique().all())

        feedback_terms = await NoteRetriever._feedback_terms(db, user_id, query, goal_text)
        scored = [NoteRetriever._score_note(note, terms, feedback_terms, goal_id, goal_material_id, goal_task_ids, goal_task_note_ids) for note in notes]
        scored = [item for item in scored if item["score"] > 0 or not terms]
        scored.sort(key=lambda item: (item["score"], item.get("updated_at") or "", item["id"]), reverse=True)
        return scored[:limit]

    @staticmethod
    async def _feedback_terms(db: AsyncSession, user_id: int, query: str, goal_text: str) -> set[str]:
        base_terms = set(_tokens(f"{query} {goal_text}"))
        result = await db.execute(
            select(UserMemory)
            .where(
                UserMemory.user_id == user_id,
                UserMemory.status == "active",
                UserMemory.review_status == CONFIRMED_REVIEW_STATUS,
                UserMemory.category == "agent_feedback",
            )
            .order_by(UserMemory.last_seen_at.desc(), UserMemory.id.desc())
            .limit(20)
        )
        matches: set[str] = set()
        for memory in result.scalars().all():
            text = f"{memory.memory_key or ''} {memory.memory_value or ''}"
            memory_terms = set(_tokens(text))
            if not base_terms or base_terms.intersection(memory_terms):
                matches.update(memory_terms)
        return matches

    @staticmethod
    def _score_note(
        note: Note,
        terms: list[str],
        feedback_terms: set[str],
        goal_id: int | None,
        material_id: int | None,
        goal_task_ids: set[int] | None = None,
        goal_task_note_ids: set[int] | None = None,
    ) -> dict[str, Any]:
        title = note.title or ""
        content = note.content or ""
        tags = _safe_tags(note.tags)
        note_type = note.note_type or "general"
        haystack = f"{title}\n{content}\n{' '.join(tags)}".lower()
        links = list(getattr(note, "links", []) or [])

        score = 0.0
        lexical_score = 0.0
        reasons: list[str] = []
        title_lower = title.lower()
        tags_lower = " ".join(tags).lower()
        for term in terms:
            needle = term.lower()
            if not needle:
                continue
            if needle in title_lower:
                lexical_score += 4.0
                reasons.append(f"title:{term}")
            if needle in tags_lower:
                lexical_score += 3.0
                reasons.append(f"tag:{term}")
            occurrences = haystack.count(needle)
            if occurrences:
                lexical_score += min(occurrences, 4) * 1.1
                reasons.append(f"keyword:{term}")
        score += min(lexical_score, 12.0)

        if goal_id is not None and any(link.link_type == "goal" and int(link.link_id) == int(goal_id) for link in links):
            score += 16.0
            reasons.append("linked_goal")
        if (
            goal_id is not None
            and (
                (goal_task_note_ids and int(note.id) in goal_task_note_ids)
                or (goal_task_ids and any(link.link_type == "task" and int(link.link_id) in goal_task_ids for link in links))
            )
        ):
            score += 4.0
            reasons.append("linked_task")
        if material_id is not None and int(note.material_id or -1) == int(material_id):
            score += 6.0
            reasons.append("same_material")
        if material_id is not None and any(link.link_type == "material" and int(link.link_id) == int(material_id) for link in links):
            score += 5.0
            reasons.append("linked_material")

        age_days = _days_since(note.updated_at or note.created_at)
        if age_days is not None:
            recency = max(0.0, 2.0 - min(age_days, 30.0) / 15.0)
            if recency:
                score += recency
                reasons.append("recent_update")

        if note_type in {"review", "summary", "method", "question"}:
            score += 1.4
            reasons.append(f"type:{note_type}")
        elif note_type in {"idea", "resource"}:
            score += 0.6
            reasons.append(f"type:{note_type}")

        note_terms = set(_tokens(f"{title} {content} {' '.join(tags)}"))
        feedback_hits = sorted(note_terms.intersection(feedback_terms))[:3]
        if feedback_hits:
            score += min(len(feedback_hits), 3) * 0.8
            reasons.append("agent_feedback")

        unique_reasons = list(dict.fromkeys(reasons))
        priority = {"linked_goal": 0, "linked_task": 1, "same_material": 2, "linked_material": 3, "agent_feedback": 4}
        ordered_reasons = sorted(
            enumerate(unique_reasons),
            key=lambda item: (priority.get(item[1], 20), item[0]),
        )
        reason = ", ".join(reason for _, reason in ordered_reasons[:8]) or "recent_note"
        return {
            "id": int(note.id),
            "title": title,
            "excerpt": _excerpt(content, terms),
            "tags": tags,
            "note_type": note_type,
            "material_id": note.material_id,
            "chapter_id": note.chapter_id,
            "updated_at": _to_iso(note.updated_at or note.created_at),
            "score": round(score, 3),
            "reason": reason,
            "route": "/notes",
        }
