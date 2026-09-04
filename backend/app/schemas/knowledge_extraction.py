"""Provider-neutral output contract for Mnemox knowledge extraction."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


ClaimKind = Literal[
    "definition",
    "principle",
    "causal",
    "recommendation",
    "comparison",
    "observation",
]
ConceptRelationType = Literal["about", "uses", "applies_to", "exemplifies"]
ClaimRelationType = Literal["supports", "contradicts", "refines", "exemplifies"]


class StrictExtractionModel(BaseModel):
    """Reject provider drift instead of silently changing domain writes."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ExtractedEvidence(StrictExtractionModel):
    quote: str = Field(min_length=1, max_length=8_000)
    char_start: int | None = Field(default=None, ge=0)
    char_end: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def validate_optional_span(self):
        if self.char_end is not None and self.char_start is None:
            raise ValueError("char_end 不能脱离 char_start 单独提供")
        if (
            self.char_start is not None
            and self.char_end is not None
            and self.char_end <= self.char_start
        ):
            raise ValueError("Evidence 字符范围无效")
        return self


class ExtractedConceptMention(StrictExtractionModel):
    text: str = Field(min_length=1, max_length=120)
    relation_type: ConceptRelationType = "about"


class ExtractedClaim(StrictExtractionModel):
    local_id: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_.:-]+$")
    statement: str = Field(min_length=1, max_length=500)
    claim_kind: ClaimKind
    evidence: list[ExtractedEvidence] = Field(min_length=1, max_length=12)
    concepts: list[ExtractedConceptMention] = Field(default_factory=list, max_length=24)
    confidence: float = Field(ge=0.0, le=1.0)


class ExtractedClaimRelation(StrictExtractionModel):
    from_local_id: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_.:-]+$")
    to_local_id: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_.:-]+$")
    relation_type: ClaimRelationType
    evidence_quote: str | None = Field(default=None, min_length=1, max_length=8_000)
    confidence: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def reject_self_relation(self):
        if self.from_local_id == self.to_local_id:
            raise ValueError("Claim relation 不能形成自环")
        return self


class KnowledgeExtractionResult(StrictExtractionModel):
    claims: list[ExtractedClaim] = Field(default_factory=list, max_length=100)
    relations: list[ExtractedClaimRelation] = Field(default_factory=list, max_length=200)

    @model_validator(mode="after")
    def validate_local_identity(self):
        local_ids = [claim.local_id for claim in self.claims]
        if len(local_ids) != len(set(local_ids)):
            raise ValueError("同一 Unit 内的 Claim local_id 必须唯一")
        known = set(local_ids)
        for relation in self.relations:
            if relation.from_local_id not in known or relation.to_local_id not in known:
                raise ValueError("Claim relation 引用了不存在的 local_id")
        return self
