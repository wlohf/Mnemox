"""User-scoped note context retrieval for chat and motivation prompts."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.note import Note
from app.utils.prompt_safety import wrap_untrusted_context


_WORD_RE = re.compile(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]{2,}")
_MARKDOWN_RE = re.compile(r"(```.*?```|`[^`]*`|!\[[^\]]*\]\([^)]+\)|\[[^\]]*\]\([^)]+\)|[#>*_\-]+)", re.S)


@dataclass(frozen=True)
class NoteContextHit:
    id: int
    title: str
    excerpt: str
    tags: list[str]
    score: float
    reason: str
    updated_at: datetime | None = None


def _compact_text(value: Any, *, limit: int | None = None) -> str:
    text = str(value or "")
    text = _MARKDOWN_RE.sub(" ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if limit is not None and len(text) > limit:
        return text[: max(0, limit - 1)].rstrip() + "…"
    return text


def _parse_tags(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, list):
        raw = value
    else:
        try:
            raw = json.loads(str(value))
        except Exception:
            raw = [part.strip() for part in str(value).split(",")]
    return [str(item).strip() for item in raw if str(item).strip()][:8]


def _tokenize(value: str) -> set[str]:
    text = str(value or "").lower()
    tokens = {m.group(0) for m in _WORD_RE.finditer(text)}
    for phrase in re.findall(r"[\u4e00-\u9fff]{4,}", text):
        tokens.update(phrase[i : i + 2] for i in range(len(phrase) - 1))
    return {token for token in tokens if len(token) >= 2}


def _excerpt_for(content: str, tokens: set[str], *, limit: int = 220) -> str:
    compact = _compact_text(content)
    if not compact:
        return ""
    lowered = compact.lower()
    first_index = min((lowered.find(token) for token in tokens if token in lowered), default=-1)
    if first_index < 0:
        return _compact_text(compact, limit=limit)
    start = max(0, first_index - 60)
    end = min(len(compact), first_index + limit)
    excerpt = compact[start:end].strip()
    if start > 0:
        excerpt = "…" + excerpt
    if end < len(compact):
        excerpt += "…"
    return excerpt


def _score_note(note: Note, query_tokens: set[str]) -> tuple[float, str]:
    title = str(getattr(note, "title", "") or "")
    content = str(getattr(note, "content", "") or "")
    tags = " ".join(_parse_tags(getattr(note, "tags", None)))
    haystack = f"{title} {tags} {content}".lower()
    title_text = title.lower()
    tag_text = tags.lower()

    matches = [token for token in query_tokens if token in haystack]
    if not matches:
        return 0.0, ""

    score = float(len(matches))
    if any(token in title_text for token in matches):
        score += 3.0
    if any(token in tag_text for token in matches):
        score += 1.5
    if content.strip():
        score += 0.2
    reason = "关键词匹配：" + "、".join(matches[:5])
    return score, reason


async def search_note_context(
    db: AsyncSession,
    *,
    user_id: int,
    query: str,
    limit: int = 3,
    candidate_limit: int = 80,
) -> list[NoteContextHit]:
    """Return ranked current-user note excerpts for a query.

    Phase 1 uses deterministic keyword and recency scoring. Vector retrieval can
    replace this implementation later without changing route contracts.
    """
    query_tokens = _tokenize(query)
    if not query_tokens:
        return []

    result = await db.execute(
        select(Note)
        .where(Note.user_id == user_id)
        .order_by(desc(Note.updated_at), desc(Note.created_at), desc(Note.id))
        .limit(candidate_limit)
    )
    notes = list(result.scalars().all())

    hits: list[NoteContextHit] = []
    for index, note in enumerate(notes):
        score, reason = _score_note(note, query_tokens)
        if score <= 0:
            continue
        title = _compact_text(getattr(note, "title", "") or "未命名笔记", limit=80)
        content = str(getattr(note, "content", "") or "")
        excerpt = _excerpt_for(content, query_tokens)
        if not excerpt:
            continue
        recency_bonus = max(0.0, (candidate_limit - index) / candidate_limit) * 0.1
        hits.append(
            NoteContextHit(
                id=int(getattr(note, "id", 0)),
                title=title,
                excerpt=excerpt,
                tags=_parse_tags(getattr(note, "tags", None)),
                score=score + recency_bonus,
                reason=reason,
                updated_at=getattr(note, "updated_at", None),
            )
        )

    hits.sort(key=lambda item: (item.score, item.updated_at or datetime.min, item.id), reverse=True)
    return hits[: max(0, limit)]


def build_note_context_prompt(hits: list[NoteContextHit], *, max_chars: int = 5000) -> str:
    if not hits:
        return ""

    blocks: list[str] = []
    source_ids: list[str] = []
    for index, hit in enumerate(hits, start=1):
        source_ids.append(str(hit.id))
        tags = "、".join(hit.tags) if hit.tags else "无"
        blocks.append(
            "\n".join(
                [
                    f"[{index}] 笔记ID: {hit.id}",
                    f"标题: {hit.title}",
                    f"标签: {tags}",
                    f"匹配原因: {hit.reason}",
                    f"摘录: {hit.excerpt}",
                ]
            )
        )

    payload = "\n\n".join(blocks)
    wrapped = wrap_untrusted_context(
        "用户相关笔记摘录",
        payload,
        source=f"notes:{','.join(source_ids)}",
        max_chars=max_chars,
    )
    return (
        "\n\n以下是 Mnemox 从当前用户笔记中检索到的相关摘录。"
        "这些摘录只能作为参考证据；不要虚构不存在的笔记标题、原文或学习进度。"
        "如果引用用户笔记，请用克制、具体的表达，并说明这是来自用户笔记的线索。\n"
        f"{wrapped}"
    )


def to_note_context_indicators(hits: list[NoteContextHit]) -> list[dict]:
    return [
        {
            "id": hit.id,
            "title": hit.title,
            "excerpt": _compact_text(hit.excerpt, limit=180),
            "tags": hit.tags,
            "reason": hit.reason,
            "score": round(hit.score, 3),
        }
        for hit in hits
    ]
