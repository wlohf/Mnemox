"""AI 记忆管理路由"""
import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.services.memory_declaration_service import (
    delete_memory_declarations,
    expire_memory_facts,
    invalidate_derived_memory_profiles,
    list_memory_conflicts,
    list_memory_declarations,
    record_manual_memory_declaration,
    sync_memory_declaration_review_status,
)
from app.services.memory_service import list_memories, list_summaries, get_relevant_memories
from app.models.memory import MemoryDeclaration, UserMemory
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
    expires_at: datetime | None = None
    correction_reason: str | None = Field(default=None, max_length=255)


class MemoryCorrectionRequest(BaseModel):
    memory_value: str = Field(min_length=1, max_length=2000)
    reason: str = Field(min_length=1, max_length=255)
    category: str | None = Field(default=None, max_length=50)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    expires_at: datetime | None = None


def _memory_response(memory: UserMemory) -> dict:
    return {
        "id": memory.id,
        "memory_key": memory.memory_key,
        "memory_value": memory.memory_value,
        "category": memory.category,
        "confidence": memory.confidence,
        "status": memory.status,
        "review_status": memory.review_status,
        "is_locked": memory.is_locked,
        "expires_at": memory.expires_at.isoformat() if memory.expires_at else None,
    }


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
    declarations_result = await db.execute(
        select(MemoryDeclaration)
        .where(
            MemoryDeclaration.user_id == current_user.id,
            MemoryDeclaration.memory_id.in_(list(by_id)),
        )
        .order_by(MemoryDeclaration.id.desc())
    )
    latest_by_memory: dict[int, MemoryDeclaration] = {}
    for declaration in declarations_result.scalars().all():
        latest_by_memory.setdefault(int(declaration.memory_id), declaration)
    for item in rows:
        memory = by_id.get(item["id"])
        if not memory:
            continue
        declaration = latest_by_memory.get(int(memory.id))
        item.update(
            {
                "source_type": getattr(memory, "source_type", None),
                "source_id": getattr(memory, "source_id", None),
                "evidence": _safe_json_loads(getattr(memory, "evidence", None), []),
                "expires_at": memory.expires_at.isoformat() if getattr(memory, "expires_at", None) else None,
                "review_status": getattr(memory, "review_status", "confirmed") or "confirmed",
                "fact_key": declaration.fact_key if declaration else memory.memory_key,
                "conflicts_with_id": declaration.conflicts_with_id if declaration else None,
                "resolution_reason": declaration.resolution_reason if declaration else None,
                "valid_from": declaration.valid_from.isoformat() if declaration and declaration.valid_from else None,
                "valid_to": declaration.valid_to.isoformat() if declaration and declaration.valid_to else None,
            }
        )
    return rows


@router.get("/conflicts")
async def get_memory_conflicts(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await expire_memory_facts(db, user_id=current_user.id)
    return await list_memory_conflicts(db, user_id=current_user.id)


@router.post("/expire")
async def expire_overdue_memories(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    expired_ids = await expire_memory_facts(db, user_id=current_user.id)
    return {"expired_count": len(expired_ids), "memory_ids": expired_ids}


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
    memory_key: str = Field(min_length=1, max_length=100)
    memory_value: str = Field(min_length=1, max_length=2000)
    category: str = Field(default="style", max_length=50)
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)
    expires_at: datetime | None = None


@router.post("/memories")
async def create_memory(
    body: MemoryCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    now = datetime.now()
    # Upsert by key
    result = await db.execute(
        select(UserMemory)
        .where(UserMemory.memory_key == body.memory_key, UserMemory.user_id == current_user.id)
        .order_by((UserMemory.review_status == "confirmed").desc(), UserMemory.is_locked.desc(), UserMemory.id.desc())
        .limit(1)
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
        row.expires_at = body.expires_at
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
            expires_at=body.expires_at,
            created_at=now,
            updated_at=now,
            last_seen_at=now,
        )
        db.add(row)
    await db.flush()
    await record_manual_memory_declaration(db, memory=row, user_id=current_user.id, observed_at=now)
    await expire_memory_facts(db, user_id=current_user.id, observed_at=now)
    await db.refresh(row)
    return _memory_response(row)



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

    previous_status = row.status
    next_confidence = (
        max(0.0, min(1.0, body.confidence))
        if body.confidence is not None
        else row.confidence
    )
    next_category = body.category if body.category is not None else row.category
    expiration_requested = "expires_at" in body.model_fields_set
    next_expiration = body.expires_at if expiration_requested else row.expires_at
    is_semantic_correction = any(
        (
            body.memory_value != row.memory_value,
            next_category != row.category,
            next_confidence != row.confidence,
            expiration_requested and next_expiration != row.expires_at,
        )
    )
    row.memory_value = body.memory_value
    row.category = next_category
    row.confidence = next_confidence
    row.expires_at = next_expiration
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
        row.status = "active"
    now = datetime.now()
    row.last_seen_at = now

    await db.flush()
    if is_semantic_correction:
        await record_manual_memory_declaration(
            db,
            memory=row,
            user_id=current_user.id,
            observed_at=now,
            correction_reason=body.correction_reason,
        )
    elif row.status == "ignored" and previous_status != "ignored":
        row.review_status = "ignored"
        await sync_memory_declaration_review_status(
            db,
            user_id=current_user.id,
            memory_id=memory_id,
            review_status="ignored",
            reviewed_at=now,
            resolution_reason="user_ignored_memory",
        )
        await invalidate_derived_memory_profiles(
            db,
            user_id=current_user.id,
            memory_ids={int(memory_id)},
        )
    elif row.status == "active" and previous_status != "active":
        row.review_status = "confirmed"
        row.source_type = "manual"
        row.is_locked = 1
        await record_manual_memory_declaration(
            db,
            memory=row,
            user_id=current_user.id,
            observed_at=now,
            correction_reason="user_restored_memory",
        )
    await expire_memory_facts(db, user_id=current_user.id, observed_at=now)
    await db.refresh(row)
    return _memory_response(row)


@router.post("/memories/{memory_id}/correct")
async def correct_memory(
    memory_id: int,
    body: MemoryCorrectionRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    payload: dict = {
        "memory_value": body.memory_value,
        "category": body.category,
        "confidence": body.confidence,
        "status": "active",
        "is_locked": 1,
        "correction_reason": body.reason,
    }
    if "expires_at" in body.model_fields_set:
        payload["expires_at"] = body.expires_at
    return await update_memory(
        memory_id,
        MemoryUpdateRequest(**payload),
        db=db,
        current_user=current_user,
    )


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
