"""Descriptive evidence contract; no inferred traits or calibrated probabilities."""
from typing import Any, Literal

from pydantic import BaseModel, Field


class BehaviorSource(BaseModel):
    kind: Literal["pomodoro"] = "pomodoro"
    id: int
    version: str
    occurred_at: str | None
    recorded_at: str | None


class FocusEvidence(BaseModel):
    source: BehaviorSource
    evidence_group: str
    origin: str
    local_date: str | None
    local_hour: int | None
    started_at: str | None
    ended_at: str | None
    outcome: Literal["completed", "early_done", "interrupted", "in_progress"]
    stop_reason: str | None
    planned_minutes: float | None
    actual_minutes: float | None
    recorded_minutes: float | None
    task_id: int | None
    task_name: str | None
    task_type: str | None
    goal_id: int | None
    included: bool
    quality_flags: list[str] = Field(default_factory=list)


class BehaviorEvidenceReport(BaseModel):
    schema_version: int = 1
    assessment: Literal["descriptive_only"] = "descriptive_only"
    user_id: int
    time_zone: str
    time_zone_source: str
    generated_at: str
    window: dict[str, Any]
    coverage: dict[str, Any]
    metrics: dict[str, Any]
    daily: list[dict[str, Any]]
    quality_counts: dict[str, int]
    limitations: list[str]
    records: list[FocusEvidence]
