"""Base classes for study agents."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.factory import AIProviderFactory
from app.models.user import User


@dataclass(slots=True)
class AgentContext:
    db: AsyncSession
    user: User


class BaseAgent:
    """Shared helper for agents that may use the configured AI provider."""

    name = "base"
    description = "基础 Agent"

    def __init__(self, context: AgentContext):
        self.context = context

    async def _chat(self, prompt: str, system_prompt: str, scenario: str, temperature: float = 0.4) -> str:
        provider = await AIProviderFactory.create_provider(
            db=self.context.db,
            scenario=scenario,
            user_id=self.context.user.id,
        )
        return await provider.chat(
            messages=[{"role": "user", "content": prompt}],
            system_prompt=system_prompt,
            temperature=temperature,
        )

    async def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError
