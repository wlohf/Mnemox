"""Base types for lightweight learning agents."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession


@dataclass
class AgentRunContext:
    db: AsyncSession
    user_id: int
    task: str = "run"
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentResult:
    agent: str
    task: str
    status: str
    summary: str
    actions: list[dict[str, Any]] = field(default_factory=list)
    data: dict[str, Any] = field(default_factory=dict)


class BaseAgent:
    name = "base"
    display_name = "Base Agent"
    description = "Base agent"

    async def run(self, ctx: AgentRunContext) -> AgentResult:
        raise NotImplementedError


def new_job_id() -> str:
    return uuid4().hex[:12]


def utc_now_iso() -> str:
    return datetime.utcnow().isoformat() + "Z"
