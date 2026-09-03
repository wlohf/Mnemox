"""Storage-neutral, fixed-path graph query contract."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, Sequence


CLAIM_PATTERNS = frozenset({"shared_concept_claims", "direct_claim_relations"})
CONCEPT_PATTERNS = frozenset({"concept_structure", "personal_evidence_by_concept"})


@dataclass(frozen=True)
class GraphHit:
    object_type: str
    object_id: int
    path_type: str
    depth: int
    confidence: float
    path: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    metadata: dict[str, Any] = field(default_factory=dict)


class GraphStore(Protocol):
    async def expand_claims(self, *, user_id: int, claim_ids: Sequence[int], patterns: Sequence[str], depth: int = 1, limit: int = 50) -> list[GraphHit]: ...
    async def expand_concepts(self, *, user_id: int, concept_ids: Sequence[int], patterns: Sequence[str], depth: int = 1, limit: int = 50) -> list[GraphHit]: ...
    async def source_claims(self, *, user_id: int, source_id: int, limit: int = 50) -> list[GraphHit]: ...
    async def rebuild_user(self, *, user_id: int) -> dict[str, Any]: ...
    async def delete_source(self, *, user_id: int, source_key: str) -> dict[str, Any]: ...
    async def health(self) -> dict[str, Any]: ...
