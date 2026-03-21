"""AI 记忆管理路由"""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.services.memory_service import list_memories, list_summaries, get_relevant_memories
from app.models.memory import UserMemory
from app.auth import get_current_user
from app.models.user import User

router = APIRouter()


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
    return await list_memories(db, user_id=current_user.id)


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

    row.memory_value = body.memory_value
    if body.category is not None:
        row.category = body.category
    if body.confidence is not None:
        row.confidence = max(0.0, min(1.0, body.confidence))
    if body.status is not None and body.status in ("active", "ignored"):
        row.status = body.status
    if body.is_locked is not None:
        row.is_locked = 1 if int(body.is_locked) == 1 else 0
    row.last_seen_at = datetime.now()

    await db.flush()
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
    await db.delete(row)
    return {"ok": True}
