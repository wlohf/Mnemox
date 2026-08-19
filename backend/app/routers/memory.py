"""AI 记忆管理路由"""
import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.services.memory_declaration_service import (
    delete_memory_declarations,
    list_memory_declarations,
    record_manual_memory_declaration,
)
from app.services.memory_service import list_memories, list_summaries, get_relevant_memories
from app.models.memory import UserMemory
from app.auth import get_current_user
from app.models.user import User

router = APIRouter()


def _safe_json_loads(text: str | None, fallback):
    if not text:
        return fallback
    try:
        return json.loads(text)
    except Exception:
        return fallback


class MemoryUpdateRequest(BaseModel):
    memory_value: str
    category: str | None = None
    confidence: float | None = None
    status: str | None = None
    is_locked: int | None = None


@router.get("/memories")
async def get_memories(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    rows = await list_memories(db, user_id=current_user.id)
    if not rows:
        return rows
    result = await db.execute(
        select(UserMemory).where(
            UserMemory.user_id == current_user.id,
            UserMemory.id.in_([row["id"] for row in rows]),
        )
    )
    by_id = {row.id: row for row in result.scalars().all()}
    for item in rows:
        memory = by_id.get(item["id"])
        if not memory:
            continue
        item.update(
            {
                "source_type": getattr(memory, "source_type", None),
                "source_id": getattr(memory, "source_id", None),
                "evidence": _safe_json_loads(getattr(memory, "evidence", None), []),
                "expires_at": memory.expires_at.isoformat() if getattr(memory, "expires_at", None) else None,
                "review_status": getattr(memory, "review_status", "confirmed") or "confirmed",
            }
        )
    return rows


@router.get("/memories/{memory_id}/declarations")
async def get_memory_declarations(
    memory_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return the user's auditable declaration history for one memory."""
    result = await db.execute(
        select(UserMemory.id).where(
            UserMemory.id == memory_id,
            UserMemory.user_id == current_user.id,
        )
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="记忆不存在")
    return await list_memory_declarations(
        db,
        user_id=current_user.id,
        memory_id=memory_id,
    )


@router.get("/relevant")
async def get_relevant(
    topic: str = Query("", description="Topic hint for relevance scoring"),
    limit: int = Query(10, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return topic-scored memories for frontend display."""
    return await get_relevant_memories(db, topic=topic, limit=limit, user_id=current_user.id)


@router.get("/summaries")
async def get_summaries(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await list_summaries(db, user_id=current_user.id)


class MemoryCreateRequest(BaseModel):
    memory_key: str
    memory_value: str
    category: str = "style"
    confidence: float = 0.8


@router.post("/memories")
async def create_memory(
    body: MemoryCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    now = datetime.now()
    # Upsert by key
    result = await db.execute(
        select(UserMemory).where(UserMemory.memory_key == body.memory_key, UserMemory.user_id == current_user.id)
    )
    row = result.scalar_one_or_none()
    if row:
        row.memory_value = body.memory_value
        row.category = body.category
        row.confidence = max(0.0, min(1.0, body.confidence))
        row.status = "active"
        row.review_status = "confirmed"
        row.source_type = "manual"
        row.source_id = None
        row.evidence = None
        row.is_locked = 1
        row.last_seen_at = now
    else:
        row = UserMemory(
            user_id=current_user.id,
            memory_key=body.memory_key,
            memory_value=body.memory_value,
            category=body.category,
            confidence=body.confidence,
            status="active",
            review_status="confirmed",
            source_type="manual",
            is_locked=1,
            created_at=now,
            updated_at=now,
            last_seen_at=now,
        )
        db.add(row)
    await db.flush()
    await record_manual_memory_declaration(db, memory=row, user_id=current_user.id, observed_at=now)
    await db.refresh(row)
    return {
        "id": row.id,
        "memory_key": row.memory_key,
        "memory_value": row.memory_value,
        "category": row.category,
        "confidence": row.confidence,
        "status": row.status,
        "is_locked": row.is_locked,
    }



@router.put("/memories/{memory_id}")
async def update_memory(
    memory_id: int,
    body: MemoryUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(UserMemory).where(UserMemory.id == memory_id, UserMemory.user_id == current_user.id)
    )
    row = result.scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="记忆不存在")

    next_confidence = (
        max(0.0, min(1.0, body.confidence))
        if body.confidence is not None
        else row.confidence
    )
    next_category = body.category if body.category is not None else row.category
    is_semantic_correction = any(
        (
            body.memory_value != row.memory_value,
            next_category != row.category,
            next_confidence != row.confidence,
        )
    )
    row.memory_value = body.memory_value
    row.category = next_category
    row.confidence = next_confidence
    if body.status is not None and body.status in ("active", "ignored"):
        row.status = body.status
    if body.is_locked is not None:
        row.is_locked = 1 if int(body.is_locked) == 1 else 0
    if is_semantic_correction:
        # A direct user correction always wins over later background extraction.
        row.is_locked = 1
        row.review_status = "confirmed"
        row.source_type = "manual"
        row.source_id = None
        row.evidence = None
    row.last_seen_at = datetime.now()

    await db.flush()
    if is_semantic_correction:
        await record_manual_memory_declaration(db, memory=row, user_id=current_user.id)
    await db.refresh(row)
    return {
        "id": row.id,
        "memory_key": row.memory_key,
        "memory_value": row.memory_value,
        "category": row.category,
        "confidence": row.confidence,
        "status": row.status,
        "is_locked": row.is_locked,
    }


@router.delete("/memories/{memory_id}")
async def delete_memory(
    memory_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(UserMemory).where(UserMemory.id == memory_id, UserMemory.user_id == current_user.id)
    )
    row = result.scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="记忆不存在")
    await delete_memory_declarations(db, user_id=current_user.id, memory_id=memory_id)
    await db.delete(row)
    return {"ok": True}
