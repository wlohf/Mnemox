"""Storage-neutral graph query contract.

The canonical graph model lives in SQL.  This module only defines business-level
query/result semantics that can be implemented by SQL, Neo4j, or another graph
execution backend without leaking ORM/Cypher/driver types upward.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, Sequence


CLAIM_PATTERNS = frozenset({"shared_concept_claims", "direct_claim_relations"})
CONCEPT_PATTERNS = frozenset({"concept_structure", "personal_evidence_by_concept"})
TraversalDirection = Literal["outgoing", "incoming", "both"]


@dataclass(frozen=True)
class GraphNodeRef:
    """Storage-neutral reference to one node in a graph path."""

    object_type: str
    object_id: int
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class GraphEdgeRef:
    """Storage-neutral edge with canonical direction and traversal orientation."""

    edge_type: str
    edge_id: int
    relation_type: str
    from_node: GraphNodeRef
    to_node: GraphNodeRef
    directed: bool = True
    traversed_forward: bool = True
    confidence: float = 1.0
    evidence_ids: tuple[int, ...] = field(default_factory=tuple)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class GraphPath:
    """Complete explainable path independent of SQLAlchemy/Cypher representations."""

    nodes: tuple[GraphNodeRef, ...]
    edges: tuple[GraphEdgeRef, ...]
    score: float = 1.0
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def depth(self) -> int:
        return len(self.edges)


@dataclass(frozen=True)
class GraphHit:
    object_type: str
    object_id: int
    path_type: str
    depth: int
    confidence: float
    # Legacy compact path kept for Association V2 API compatibility. New
    # graph-native features should use ``graph_path`` instead.
    path: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    metadata: dict[str, Any] = field(default_factory=dict)
    graph_path: GraphPath | None = None


class GraphCapabilityUnsupported(RuntimeError):
    """Raised when a backend intentionally does not implement a graph-native capability."""


class GraphStore(Protocol):
    async def expand_claims(self, *, user_id: int, claim_ids: Sequence[int], patterns: Sequence[str], depth: int = 1, limit: int = 50) -> list[GraphHit]: ...
    async def expand_concepts(self, *, user_id: int, concept_ids: Sequence[int], patterns: Sequence[str], depth: int = 1, limit: int = 50) -> list[GraphHit]: ...
    async def source_claims(self, *, user_id: int, source_id: int, limit: int = 50) -> list[GraphHit]: ...
    async def find_concept_paths(
        self,
        *,
        user_id: int,
        start_concept_ids: Sequence[int],
        target_concept_ids: Sequence[int],
        relation_types: Sequence[str],
        direction: TraversalDirection = "outgoing",
        max_depth: int = 4,
        limit: int = 10,
    ) -> list[GraphPath]: ...
    async def rebuild_user(self, *, user_id: int) -> dict[str, Any]: ...
    async def delete_source(self, *, user_id: int, source_key: str) -> dict[str, Any]: ...
    async def health(self) -> dict[str, Any]: ...
