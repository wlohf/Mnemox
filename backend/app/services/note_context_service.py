"""User-scoped note context retrieval for chat and motivation prompts."""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.context_store import ContextItem, get_context_store
from app.utils.prompt_safety import wrap_untrusted_context


_MARKDOWN_RE = re.compile(r"(```.*?```|`[^`]*`|!\[[^\]]*\]\([^)]+\)|\[[^\]]*\]\([^)]+\)|[#>*_\-]+)", re.S)
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class NoteContextHit:
    id: int
    title: str
    excerpt: str
    tags: list[str]
    score: float
    reason: str
    updated_at: datetime | None = None
    retrieval_mode: str = "unknown"


def _compact_text(value: Any, *, limit: int | None = None) -> str:
    text = str(value or "")
    text = _MARKDOWN_RE.sub(" ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if limit is not None and len(text) > limit:
        return text[: max(0, limit - 1)].rstrip() + "…"
    return text


def _context_item_to_note_hit(item: ContextItem) -> NoteContextHit:
    metadata = item.metadata if isinstance(item.metadata, dict) else {}
    raw_tags = metadata.get("tags", [])
    tags = [str(tag).strip() for tag in raw_tags if str(tag).strip()][:8] if isinstance(raw_tags, list) else []
    updated_at = metadata.get("updated_at")
    if not isinstance(updated_at, datetime):
        updated_at = None
    return NoteContextHit(
        id=int(item.source_id),
        title=_compact_text(item.title or "未命名笔记", limit=80),
        excerpt=_compact_text(item.excerpt),
        tags=tags,
        score=float(item.score or 0.0),
        reason=str(metadata.get("reason") or ""),
        updated_at=updated_at,
        retrieval_mode=str(metadata.get("retrieval_mode") or "unknown"),
    )


async def search_note_context(
    db: AsyncSession,
    *,
    user_id: int,
    query: str,
    limit: int = 3,
) -> list[NoteContextHit]:
    """Return ranked current-user note excerpts through the ContextStore boundary."""
    if not str(query or "").strip():
        return []
    try:
        items = await get_context_store().retrieve(
            db,
            user_id,
            query,
            top_k=max(1, min(int(limit or 3), 12)),
            source_types=("note",),
        )
    except Exception:
        logger.warning(
            "event=contextstore.retrieve status=failure source_types=note",
            exc_info=True,
        )
        raise

    hits = [_context_item_to_note_hit(item) for item in items if item.source_type == "note"]
    retrieval_mode = hits[0].retrieval_mode if hits else "unknown"
    logger.info(
        "event=contextstore.retrieve status=success source_types=note result_count=%s retrieval_mode=%s",
        len(hits),
        retrieval_mode,
    )
    return hits


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
