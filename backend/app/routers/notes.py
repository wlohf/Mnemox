"""笔记系统路由（MVP）"""
import json
import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, or_
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.note import Note, NoteLink
from app.ai.factory import AIProviderFactory
from app.auth import get_current_user
from app.models.user import User

router = APIRouter()
logger = logging.getLogger(__name__)


class NoteLinkIn(BaseModel):
    link_type: str
    link_id: int


class NoteCreate(BaseModel):
    title: str
    content: str
    note_type: Optional[str] = "general"
    material_id: Optional[int] = None
    chapter_id: Optional[int] = None
    tags: Optional[List[str]] = None
    links: Optional[List[NoteLinkIn]] = None


class NoteUpdate(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    note_type: Optional[str] = None
    material_id: Optional[int] = None
    chapter_id: Optional[int] = None
    tags: Optional[List[str]] = None
    links: Optional[List[NoteLinkIn]] = None


class NoteSuggestRequest(BaseModel):
    content: str
    context: Optional[str] = None


def _heuristic_suggest(content: str) -> dict:
    clean = (content or "").strip()
    if not clean:
        return {"title": "新笔记", "tags": ["摘录"]}

    first = clean.splitlines()[0].strip("#* -\t")
    title = first[:30] if first else "学习摘录"

    tags = []
    rules = [
        ("复习", "复习"),
        ("总结", "总结"),
        ("公式", "公式"),
        ("错题", "错题"),
        ("任务", "任务"),
        ("计划", "计划"),
    ]
    for kw, tag in rules:
        if kw in clean and tag not in tags:
            tags.append(tag)
    if not tags:
        tags = ["学习", "摘录"]
    return {"title": title or "学习摘录", "tags": tags[:5]}


def _to_item(note: Note) -> dict:
    created_at = getattr(note, "created_at", None)
    updated_at = getattr(note, "updated_at", None)
    return {
        "id": note.id,
        "title": note.title,
        "content": note.content,
        "note_type": note.note_type,
        "material_id": note.material_id,
        "chapter_id": note.chapter_id,
        "tags": _safe_tags(note.tags),
        "links": [
            {"id": l.id, "link_type": l.link_type, "link_id": l.link_id}
            for l in (note.links or [])
        ],
        "created_at": created_at.isoformat() if created_at else None,
        "updated_at": updated_at.isoformat() if updated_at else None,
    }


def _safe_tags(raw: Optional[str]) -> List[str]:
    if not raw:
        return []
    try:
        import json
        arr = json.loads(raw)
        if isinstance(arr, list):
            return [str(x).strip() for x in arr if str(x).strip()][:12]
    except Exception as e:
        logger.warning("解析笔记标签失败，raw=%s, err=%s", raw, e)
    return []


@router.get("")
async def list_notes(
    q: Optional[str] = Query(None),
    note_type: Optional[str] = Query(None),
    link_type: Optional[str] = Query(None),
    link_id: Optional[int] = Query(None),
    tag: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = select(Note).options(selectinload(Note.links)).where(Note.user_id == current_user.id)
    if q:
        query = query.where(or_(Note.title.ilike(f"%{q}%"), Note.content.ilike(f"%{q}%")))
    if note_type:
        query = query.where(Note.note_type == note_type)

    result = await db.execute(query.order_by(Note.updated_at.desc(), Note.id.desc()))
    notes = result.scalars().all()

    out = []
    for n in notes:
        if link_type and link_id is not None:
            if not any(l.link_type == link_type and l.link_id == link_id for l in (n.links or [])):
                continue
        if tag:
            tags = _safe_tags(n.tags)
            if tag not in tags:
                continue
        out.append(_to_item(n))
    return out


@router.get("/{note_id}")
async def get_note(
    note_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Note).options(selectinload(Note.links)).where(Note.id == note_id, Note.user_id == current_user.id)
    )
    note = result.scalar_one_or_none()
    if not note:
        raise HTTPException(status_code=404, detail="笔记不存在")
    return _to_item(note)


@router.post("")
async def create_note(
    body: NoteCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    note = Note(
        user_id=current_user.id,
        title=body.title,
        content=body.content,
        tags=json.dumps(body.tags or [], ensure_ascii=False),
        note_type=body.note_type,
        material_id=body.material_id,
        chapter_id=body.chapter_id,
    )
    db.add(note)
    await db.flush()

    for link in body.links or []:
        db.add(NoteLink(note_id=note.id, link_type=link.link_type, link_id=link.link_id))

    await db.flush()
    result = await db.execute(
        select(Note).options(selectinload(Note.links)).where(Note.id == note.id, Note.user_id == current_user.id)
    )
    note = result.scalar_one()
    return _to_item(note)


@router.put("/{note_id}")
async def update_note(
    note_id: int,
    body: NoteUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Note).options(selectinload(Note.links)).where(Note.id == note_id, Note.user_id == current_user.id)
    )
    note = result.scalar_one_or_none()
    if not note:
        raise HTTPException(status_code=404, detail="笔记不存在")

    if body.title is not None:
        setattr(note, "title", body.title)
    if body.content is not None:
        setattr(note, "content", body.content)
    if body.note_type is not None:
        setattr(note, "note_type", body.note_type)
    if body.tags is not None:
        setattr(note, "tags", json.dumps(body.tags, ensure_ascii=False))
    if body.material_id is not None:
        setattr(note, "material_id", body.material_id)
    if body.chapter_id is not None:
        setattr(note, "chapter_id", body.chapter_id)

    if body.links is not None:
        old_links = list(note.links or [])
        for l in old_links:
            await db.delete(l)
        await db.flush()
        for link in body.links:
            db.add(NoteLink(note_id=note.id, link_type=link.link_type, link_id=link.link_id))

    await db.flush()
    result = await db.execute(
        select(Note).options(selectinload(Note.links)).where(Note.id == note.id, Note.user_id == current_user.id)
    )
    note = result.scalar_one()
    return _to_item(note)


@router.delete("/{note_id}")
async def delete_note(
    note_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Note).options(selectinload(Note.links)).where(Note.id == note_id, Note.user_id == current_user.id)
    )
    note = result.scalar_one_or_none()
    if not note:
        raise HTTPException(status_code=404, detail="笔记不存在")
    await db.delete(note)
    return {"ok": True}


@router.post("/suggest-metadata")
async def suggest_note_metadata(
    body: NoteSuggestRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    fallback = _heuristic_suggest(body.content)

    prompt = (
        "请为以下笔记内容生成一个简短标题和 2-5 个标签。"
        "只输出 JSON：{\"title\":\"...\",\"tags\":[\"...\"]}。\n"
        f"上下文：{body.context or ''}\n"
        f"内容：{(body.content or '')[:1200]}"
    )

    try:
        provider = await AIProviderFactory.create_provider(
            db=db,
            scenario="note_metadata",
            user_id=current_user.id,
        )
        raw = await provider.chat(
            messages=[{"role": "user", "content": prompt}],
            system_prompt="你是笔记整理助手，只输出 JSON。",
            temperature=0.2,
        )
        import json
        import re

        text = (raw or "").strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?", "", text, flags=re.IGNORECASE).strip()
            if text.endswith("```"):
                text = text[:-3].strip()
        obj = json.loads(text)
        title = str(obj.get("title", "")).strip() or fallback["title"]
        tags = obj.get("tags", fallback["tags"])
        if not isinstance(tags, list):
            tags = fallback["tags"]
        tags = [str(t).strip() for t in tags if str(t).strip()][:5]
        if not tags:
            tags = fallback["tags"]
        return {"title": title[:50], "tags": tags}
    except Exception:
        return fallback
