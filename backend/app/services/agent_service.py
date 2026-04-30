"""Service layer for study agents."""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import AgentContext
from app.agents.manager import AgentManager
from app.models.user import User


class AgentService:
    def __init__(self, db: AsyncSession, user: User):
        self.context = AgentContext(db=db, user=user)

    def list_agents(self) -> list[dict[str, str]]:
        return AgentManager.list_agents()

    async def run_agent(self, agent_name: str, payload: dict) -> dict:
        agent = AgentManager.create(agent_name, self.context)
        result = await agent.run(payload)
        return {"agent": agent_name, "result": result}
