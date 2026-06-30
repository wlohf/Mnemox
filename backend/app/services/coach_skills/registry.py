"""Coach skill registry."""
from __future__ import annotations

from app.services.coach_skills.base import CoachSkill
from app.services.coach_skills.frustration_support import FrustrationSupportSkill
from app.services.coach_skills.low_motivation import LowMotivationSkill
from app.services.coach_skills.minimum_next_step import MinimumNextStepSkill
from app.services.coach_skills.planning_rescue import PlanningRescueSkill
from app.services.coach_skills.reflection_prompt import ReflectionPromptSkill
from app.services.coach_skills.restart_after_interruption import RestartAfterInterruptionSkill
from app.services.coach_skills.review_debt_rescue import ReviewDebtRescueSkill


class CoachSkillRegistry:
    def __init__(self) -> None:
        skills: list[CoachSkill] = [
            LowMotivationSkill(),
            FrustrationSupportSkill(),
            RestartAfterInterruptionSkill(),
            ReviewDebtRescueSkill(),
            PlanningRescueSkill(),
            MinimumNextStepSkill(),
            ReflectionPromptSkill(),
        ]
        self._skills = {skill.id: skill for skill in skills}

    def get(self, skill_id: str) -> CoachSkill | None:
        return self._skills.get(skill_id)

    def list(self) -> list[dict[str, object]]:
        return [
            {
                "id": skill.id,
                "display_name": skill.display_name,
                "description": skill.description,
                "trigger_event_types": sorted(skill.trigger_event_types),
                "required_context": sorted(skill.required_context),
                "tone_rules": skill.tone_rules,
                "safety_rules": skill.safety_rules,
            }
            for skill in self._skills.values()
        ]


coach_skill_registry = CoachSkillRegistry()
