"""Strict model output contract; probabilities supplied by the model are rejected."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid')


class EvidenceRef(StrictModel):
    id: str
    version: str
    quote: str = Field(min_length=1, max_length=500)


class Condition(StrictModel):
    field: Literal['task_type', 'local_hour', 'outcome', 'stop_reason', 'actual_minutes', 'planned_minutes']
    op: Literal['eq', 'ge', 'le'] = 'eq'
    value: str | float


class ProspectiveTest(StrictModel):
    """Frozen observable criterion, not a fixed inventory of user traits."""
    scope: list[Condition] = Field(default_factory=list, max_length=5)
    outcome: Condition
    description: str = Field(min_length=1, max_length=500)


class Candidate(StrictModel):
    statement: str = Field(min_length=4, max_length=1000)
    context: str = Field(min_length=1, max_length=1000)
    support: list[EvidenceRef] = Field(min_length=1, max_length=12)
    counter: list[EvidenceRef] = Field(default_factory=list, max_length=12)
    context_refs: list[EvidenceRef] = Field(default_factory=list, max_length=8)
    unknowns: list[str] = Field(min_length=1, max_length=12)
    next_signal: str = Field(min_length=1, max_length=1000)
    prospective_test: ProspectiveTest | None = None
    replaces: str | None = None


class CandidateBatch(StrictModel):
    candidates: list[Candidate] = Field(default_factory=list, max_length=3)
    abstention_reason: str = Field(default='', max_length=1000)


class PreferenceUpdate(StrictModel):
    analysis_enabled: bool = False
    graph_enabled: bool = False
    consume_enabled: bool = False


class HypothesisReview(StrictModel):
    version: int = Field(ge=1)
    action: Literal['correct', 'ignore', 'restore', 'withdraw', 'delete']
    correction: str | None = Field(default=None, max_length=1000)
