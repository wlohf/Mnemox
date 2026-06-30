"""Coach skill base contracts."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class CoachSkillContext:
    user_id: int
    event: dict[str, Any]
    snapshot: dict[str, Any]
    policy: dict[str, Any]
    recent_feedback: list[dict[str, Any]] = field(default_factory=list)


@dataclass(slots=True)
class CoachSkillResult:
    title: str
    body: str
    suggested_action: dict[str, Any]
    route: str | None = None
    requires_confirmation: bool = False
    draft: dict[str, Any] | None = None
    explainability: dict[str, Any] | None = None


class CoachSkill:
    id: str = ""
    display_name: str = ""
    description: str = ""
    trigger_event_types: set[str] = set()
    required_context: set[str] = set()
    output_schema: dict[str, Any] = {}
    tone_rules: list[str] = []
    safety_rules: list[str] = []

    async def generate(self, ctx: CoachSkillContext) -> CoachSkillResult:
        raise NotImplementedError


def trim_text(value: Any, limit: int) -> str:
    text = " ".join(str(value or "").split())
    return text[:limit]


def explain_with_context(ctx: CoachSkillContext, reason: str, signals: list[str] | None = None) -> dict[str, Any]:
    coach_context = ctx.snapshot.get("coach_context") or {}
    sources = coach_context.get("sources") if isinstance(coach_context, dict) else []
    return {
        "reason": reason,
        "signals": signals or [],
        "sources": sources if isinstance(sources, list) else [],
        "context_terms": coach_context.get("query_terms", []) if isinstance(coach_context, dict) else [],
    }
