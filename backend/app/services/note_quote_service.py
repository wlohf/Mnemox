"""笔记自引服务：低动力场景引用用户自己的笔记原文。

产品约束（路线图"自引激励收尾"）：
- 只引用原文摘录并注明出处（标题 + 时间），不改写、不编造。
- 防疲劳：同一摘录在冷却期（默认 14 天）内不重复引用。
- 反馈闭环：引用随 Coach nudge 落库，nudge 反馈回写到使用记录。
- 降级纪律：本服务任何失败都不应阻塞 Coach / 激励主流程（调用方需捕获）。
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.note import Note
from app.models.note_quote import NoteQuoteUsage
from app.services.note_excerpt import (
    excerpt_hash,
    extract_note_excerpt,
    normalize_note_title,
    should_reference_title,
)

QUOTE_COOLDOWN_DAYS = 14
_SCAN_LIMIT = 20
# 心得类笔记优先于普通笔记（note_type: general | summary | review）
_PREFERRED_NOTE_TYPES = ("review", "summary")


async def recently_used_hashes(
    db: AsyncSession,
    user_id: int,
    *,
    now: datetime | None = None,
    cooldown_days: int = QUOTE_COOLDOWN_DAYS,
) -> set[str]:
    """返回冷却期内已被引用的摘录指纹集合。"""
    now = now or datetime.now()
    threshold = now - timedelta(days=max(1, int(cooldown_days)))
    result = await db.execute(
        select(NoteQuoteUsage.excerpt_hash).where(
            NoteQuoteUsage.user_id == user_id,
            NoteQuoteUsage.quoted_at >= threshold,
        )
    )
    return {row[0] for row in result.all() if row and row[0]}


def _quote_candidate(note: Note) -> dict[str, Any] | None:
    excerpt = extract_note_excerpt(str(getattr(note, "content", "") or ""))
    if not excerpt:
        return None
    noted_at = getattr(note, "created_at", None) or getattr(note, "updated_at", None)
    title = normalize_note_title(str(getattr(note, "title", "") or ""))
    return {
        "note_id": int(note.id),
        "title": title,
        "excerpt": excerpt,
        "excerpt_hash": excerpt_hash(excerpt),
        "noted_at": noted_at.isoformat() if noted_at else None,
        "reference_title": should_reference_title(str(getattr(note, "title", "") or "")),
    }


async def select_note_quote(
    db: AsyncSession,
    user_id: int,
    *,
    now: datetime | None = None,
    cooldown_days: int = QUOTE_COOLDOWN_DAYS,
) -> dict[str, Any] | None:
    """挑选一条可引用的笔记摘录；冷却期内的摘录不会被选中。

    选择顺序：心得类（review/summary）优先，其后按更新时间从新到旧。
    没有可用摘录时返回 None（调用方按无引用路径继续）。
    """
    result = await db.execute(
        select(Note)
        .where(Note.user_id == user_id)
        .order_by(Note.updated_at.desc(), Note.id.desc())
        .limit(_SCAN_LIMIT)
    )
    notes = list(result.scalars().all())
    if not notes:
        return None

    used = await recently_used_hashes(db, user_id, now=now, cooldown_days=cooldown_days)

    def _iter_by_preference():
        for note in notes:
            if str(getattr(note, "note_type", "") or "") in _PREFERRED_NOTE_TYPES:
                yield note
        for note in notes:
            if str(getattr(note, "note_type", "") or "") not in _PREFERRED_NOTE_TYPES:
                yield note

    seen_hashes: set[str] = set()
    for note in _iter_by_preference():
        candidate = _quote_candidate(note)
        if not candidate:
            continue
        digest = candidate["excerpt_hash"]
        if digest in used or digest in seen_hashes:
            seen_hashes.add(digest)
            continue
        return candidate
    return None


def _when_phrase(noted_at: str | None) -> str:
    if not noted_at:
        return "之前"
    try:
        moment = datetime.fromisoformat(noted_at)
    except ValueError:
        return "之前"
    if moment.year == datetime.now().year:
        return f"{moment.month}月{moment.day}日"
    return f"{moment.year}年{moment.month}月"


def format_note_quote_line(quote: dict[str, Any]) -> str:
    """把摘录格式化为一句克制的引用（原文 + 出处，不加工内容）。"""
    excerpt = str(quote.get("excerpt") or "").strip().rstrip("，。；;、 ")
    when = _when_phrase(quote.get("noted_at"))
    if quote.get("reference_title"):
        return f"还记得{when}你在《{quote.get('title')}》里写下的吗——「{excerpt}」"
    return f"还记得{when}你写下的这句吗——「{excerpt}」"


async def record_note_quote_usage(
    db: AsyncSession,
    user_id: int,
    quote: dict[str, Any],
    *,
    channel: str,
    nudge_id: str | None = None,
    now: datetime | None = None,
) -> None:
    """记录一次引用（用于冷却与反馈回写）。不 commit，随调用方事务提交。"""
    excerpt = str(quote.get("excerpt") or "")
    if not excerpt:
        return
    db.add(
        NoteQuoteUsage(
            user_id=user_id,
            note_id=quote.get("note_id"),
            excerpt_hash=str(quote.get("excerpt_hash") or excerpt_hash(excerpt)),
            excerpt_preview=excerpt[:200],
            channel=(channel or "coach")[:40],
            nudge_id=nudge_id,
            quoted_at=now or datetime.now(),
        )
    )
    await db.flush()


async def attach_note_quote_feedback(
    db: AsyncSession,
    user_id: int,
    nudge_id: str,
    outcome: str,
) -> int:
    """把 nudge 反馈回写到对应的引用使用记录，返回更新行数。"""
    if not nudge_id:
        return 0
    result = await db.execute(
        update(NoteQuoteUsage)
        .where(
            NoteQuoteUsage.user_id == user_id,
            NoteQuoteUsage.nudge_id == nudge_id,
        )
        .values(feedback_outcome=(outcome or "")[:40])
    )
    return int(result.rowcount or 0)
