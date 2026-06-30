"""Agent long-memory review endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models.user import User
from app.services.agent_long_memory_service import (
    confirm_memory_candidate,
    get_core_profile,
    ignore_memory_candidate,
    list_memory_candidates,
    rebuild_core_profile,
)
from app.services.agent_memory_learning_service import run_agent_memory_learning

router = APIRouter()


class ConfirmCandidateRequest(BaseModel):
    lock: bool = False


class IgnoreCandidateRequest(BaseModel):
    reason: str | None = None


@router.get("/candidates")
async def get_agent_memory_candidates(
    limit: int = Query(100, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await list_memory_candidates(db, int(current_user.id), limit=limit)


@router.post("/candidates/{candidate_id}/confirm")
async def confirm_agent_memory_candidate(
    candidate_id: int,
    body: ConfirmCandidateRequest | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        result = await confirm_memory_candidate(db, int(current_user.id), candidate_id, lock=bool(body and body.lock))
        await rebuild_core_profile(db, int(current_user.id))
        return result
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/candidates/{candidate_id}/ignore")
async def ignore_agent_memory_candidate(
    candidate_id: int,
    body: IgnoreCandidateRequest | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        result = await ignore_memory_candidate(
            db,
            int(current_user.id),
            candidate_id,
            reason=(body.reason if body else None) or "ignored",
        )
        await rebuild_core_profile(db, int(current_user.id))
        return result
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/run-learning")
async def run_agent_memory_learning_endpoint(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await run_agent_memory_learning(db, int(current_user.id))


@router.get("/core-profile")
async def get_agent_core_profile(
    rebuild: bool = Query(False, description="重新生成核心画像"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if rebuild:
        return await rebuild_core_profile(db, int(current_user.id))
    return await get_core_profile(db, int(current_user.id))
