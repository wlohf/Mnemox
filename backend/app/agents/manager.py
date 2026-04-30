"""Agent manager and registry."""
from __future__ import annotations

from app.agents.base import AgentContext, BaseAgent
from app.agents.chat_agent import ChatAgent
from app.agents.review_agent import ReviewAgent
from app.agents.study_plan_agent import StudyPlanAgent


class AgentManager:
    _registry: dict[str, type[BaseAgent]] = {
        ChatAgent.name: ChatAgent,
        ReviewAgent.name: ReviewAgent,
        StudyPlanAgent.name: StudyPlanAgent,
    }

    @classmethod
    def list_agents(cls) -> list[dict[str, str]]:
        return [
            {"name": name, "description": agent_cls.description}
            for name, agent_cls in cls._registry.items()
        ]

    @classmethod
    def create(cls, name: str, context: AgentContext) -> BaseAgent:
        agent_cls = cls._registry.get(name)
        if not agent_cls:
            raise KeyError(name)
        return agent_cls(context)
