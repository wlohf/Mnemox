"""Agent API routes."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models.user import User
from app.services.agent_service import AgentService

router = APIRouter()


class AgentRunRequest(BaseModel):
    payload: dict[str, Any] = {}


@router.get("")
async def list_agents(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return AgentService(db, current_user).list_agents()


@router.post("/{agent_name}/run")
async def run_agent(
    agent_name: str,
    body: AgentRunRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = AgentService(db, current_user)
    try:
        return await service.run_agent(agent_name, body.payload)
    except KeyError:
        raise HTTPException(status_code=404, detail="Agent 不存在")
