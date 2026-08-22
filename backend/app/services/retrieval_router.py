"""Unified retrieval router for user-scoped learning context.

The router owns cross-source routing and fusion. Individual source backends own
source-specific retrieval: the material backend may internally fuse Chroma and
keyword candidates, while this router treats the resulting material list as one
source alongside notes, confirmed memories, concepts, and learner state.
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any, Optional, Sequence

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.concept import Concept, ConceptEdge
from app.models.learner_model import UserConceptState
from app.models.material import Material
from app.models.memory import UserMemory
from app.services.context_store import L0, L1, L2, ContextItem, ContextStore, get_context_store
from app.services.material_retrieval_backend import (
    MaterialRetrievalBackend,
    MaterialSearchScope,
    create_material_retrieval_backend,
)

ROUTER_SOURCE_TYPES = ("material", "note", "memory", "concept", "learner_state")
CONFIRMED_REVIEW_STATUS = "confirmed"
_QUERY_TOKEN_RE = re.compile(r"[a-z0-9_]+|[\u4e00-\u9fff]+", re.I)


@dataclass(frozen=True)
class RetrievalHit:
    source_type: str
    source_id: int | str
    title: str
    excerpt: str
    score: float
    level: int = L1
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def key(self) -> str:
        if self.source_type == "material":
            material_id = self.metadata.get("material_id", self.source_id)
            chunk_index = self.metadata.get("chunk_index", 0)
            return f"material:{material_id}:chunk:{chunk_index}"
        return f"{self.source_type}:{self.source_id}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_type": self.source_type,
            "source_id": self.source_id,
            "title": self.title,
            "excerpt": self.excerpt,
            "text": self.excerpt,
            "score": round(float(self.score), 6),
            "level": self.level,
            "metadata": dict(self.metadata),
            "source": self.metadata.get("source") or self.key,
        }

    def to_material_chunk(self) -> dict[str, Any]:
        if self.source_type != "material":
            raise ValueError("Only material hits can be converted to material chunks")
        return {
            "text": self.excerpt,
            "score": float(self.score),
            "material_id": int(self.metadata.get("material_id", self.source_id)),
            "material_title": self.title,
            "chunk_index": int(self.metadata.get("chunk_index", 0)),
            "source": self.metadata.get("source") or self.key,
            "backend": self.metadata.get("backend", "unknown"),
            "backend_scores": dict(self.metadata.get("backend_scores") or {}),
            "backend_ranks": dict(self.metadata.get("backend_ranks") or {}),
        }


@dataclass(frozen=True)
class RetrievalDiagnostics:
    requested_sources: tuple[str, ...]
    successful_sources: tuple[str, ...]
    degraded_sources: dict[str, str]
    candidate_counts: dict[str, int]
    fusion: str


@dataclass(frozen=True)
class RetrievalResponse:
    hits: list[RetrievalHit]
    diagnostics: RetrievalDiagnostics


def _query_terms(value: str) -> tuple[str, ...]:
    text = str(value or "").lower().strip()
    if not text:
        return ()
    tokens: list[str] = []
    for match in _QUERY_TOKEN_RE.finditer(text):
        token = match.group(0)
        tokens.append(token)
        if re.fullmatch(r"[\u4e00-\u9fff]+", token) and len(token) >= 4:
            tokens.extend(token[index : index + 2] for index in range(len(token) - 1))
    return tuple(dict.fromkeys(token for token in tokens if token))


def _text_score(query: str, title: str, body: str, extra: str = "") -> float:
    terms = _query_terms(query)
    if not terms:
        return 0.1
    title_l = str(title or "").lower()
    body_l = str(body or "").lower()
    extra_l = str(extra or "").lower()
    query_l = str(query or "").lower().strip()
    score = 0.0
    if query_l and query_l in title_l:
        score += 5.0
    if query_l and query_l in body_l:
        score += 3.0
    for term in terms:
        if term in title_l:
            score += 2.0
        if term in extra_l:
            score += 1.25
        if term in body_l:
            score += 0.75
    return score


def _context_item_to_hit(item: ContextItem) -> RetrievalHit:
    metadata = dict(item.metadata or {})
    metadata.setdefault("source", f"{item.source_type}:{item.source_id}")
    metadata.setdefault("retrieval_backend", metadata.get("retrieval_mode", "context_store"))
    return RetrievalHit(
        source_type=item.source_type,
        source_id=int(item.source_id),
        title=str(item.title or ""),
        excerpt=str(item.excerpt or ""),
        score=float(item.score or 0.0),
        metadata=metadata,
    )


class RetrievalRouter:
    """Route, normalize, fuse, and tier-load current-user retrieval results."""

    def __init__(
        self,
        db: AsyncSession,
        *,
        material_backend: MaterialRetrievalBackend | None = None,
        context_store: ContextStore | None = None,
        material_mode: str = "hybrid",
        rrf_k: int = 60,
    ) -> None:
        self.db = db
        self.context_store = context_store or get_context_store()
        self.material_backend = material_backend or create_material_retrieval_backend(
            db, mode=material_mode
        )
        self.rrf_k = max(1, int(rrf_k))

    async def search(
        self,
        query: str,
        *,
        user_id: int,
        source_types: Sequence[str] = ROUTER_SOURCE_TYPES,
        top_k: int = 8,
        per_source_k: int | None = None,
        material_ids: Optional[Sequence[int]] = None,
        material_id_min: int | None = None,
        material_id_max: int | None = None,
        project_id: int | None = None,
        load_level: int = L1,
    ) -> list[RetrievalHit]:
        response = await self.search_with_diagnostics(
            query,
            user_id=user_id,
            source_types=source_types,
            top_k=top_k,
            per_source_k=per_source_k,
            material_ids=material_ids,
            material_id_min=material_id_min,
            material_id_max=material_id_max,
            project_id=project_id,
            load_level=load_level,
        )
        return response.hits

    async def search_with_diagnostics(
        self,
        query: str,
        *,
        user_id: int,
        source_types: Sequence[str] = ROUTER_SOURCE_TYPES,
        top_k: int = 8,
        per_source_k: int | None = None,
        material_ids: Optional[Sequence[int]] = None,
        material_id_min: int | None = None,
        material_id_max: int | None = None,
        project_id: int | None = None,
        load_level: int = L1,
    ) -> RetrievalResponse:
        requested = tuple(dict.fromkeys(str(source).strip() for source in source_types))
        unknown = [source for source in requested if source not in ROUTER_SOURCE_TYPES]
        if unknown:
            raise ValueError(f"Unsupported retrieval source(s): {', '.join(unknown)}")
        limit = max(1, min(int(top_k or 8), 50))
        source_limit = max(limit, min(int(per_source_k or limit * 3), 80))
        if not requested:
            diagnostics = RetrievalDiagnostics(requested, (), {}, {}, "none")
            return RetrievalResponse([], diagnostics)

        results: dict[str, list[RetrievalHit]] = {}
        degraded: dict[str, str] = {}
        for source in requested:
            try:
                if source == "material":
                    hits = await self._search_materials(
                        query,
                        user_id=user_id,
                        limit=source_limit,
                        material_ids=material_ids,
                        material_id_min=material_id_min,
                        material_id_max=material_id_max,
                        project_id=project_id,
                    )
                elif source == "note":
                    hits = await self._search_context_store(query, user_id, source, source_limit)
                elif source == "memory":
                    hits = await self._search_memories(query, user_id, source_limit)
                elif source == "concept":
                    hits = await self._search_concepts(query, user_id, source_limit)
                else:
                    hits = await self._search_learner_state(query, user_id, source_limit)
                results[source] = hits
            except Exception as exc:
                degraded[source] = type(exc).__name__
                results[source] = []

        non_empty = {source: hits for source, hits in results.items() if hits}
        if len(non_empty) <= 1:
            fused = next(iter(non_empty.values()), [])[:limit]
            fusion = "direct"
        else:
            fused = self._rrf_fuse(non_empty, limit)
            fusion = "rrf"

        if load_level != L1:
            loaded: list[RetrievalHit] = []
            for hit in fused:
                content = await self.load_hit(hit, user_id=user_id, level=load_level)
                loaded.append(replace(hit, excerpt=content, level=load_level))
            fused = loaded

        diagnostics = RetrievalDiagnostics(
            requested_sources=requested,
            successful_sources=tuple(source for source in requested if source not in degraded),
            degraded_sources=degraded,
            candidate_counts={source: len(hits) for source, hits in results.items()},
            fusion=fusion,
        )
        return RetrievalResponse(fused, diagnostics)

    async def _search_materials(
        self,
        query: str,
        *,
        user_id: int,
        limit: int,
        material_ids: Optional[Sequence[int]],
        material_id_min: int | None,
        material_id_max: int | None,
        project_id: int | None,
    ) -> list[RetrievalHit]:
        if not str(query or "").strip():
            items = await self.context_store.retrieve(
                self.db,
                user_id,
                "",
                top_k=limit,
                source_types=("material",),
            )
            hits: list[RetrievalHit] = []
            for item in items:
                if item.source_type != "material":
                    continue
                hit = _context_item_to_hit(item)
                metadata = dict(hit.metadata)
                metadata.update(
                    {
                        "material_id": int(hit.source_id),
                        "chunk_index": 0,
                        "source": f"material:{hit.source_id}",
                        "backend": "context_store",
                        "score_normalization": "context_store",
                    }
                )
                hits.append(replace(hit, metadata=metadata))
            return hits[:limit]

        scope = MaterialSearchScope(
            user_id=user_id,
            material_ids=material_ids,
            material_id_min=material_id_min,
            material_id_max=material_id_max,
            project_id=project_id,
        )
        chunks = await self.material_backend.search(query, scope=scope, top_k=limit)
        if not chunks:
            return []

        raw_scores = [max(0.0, float(chunk.score)) for chunk in chunks]
        max_raw_score = max(raw_scores) or 1.0
        hits: list[RetrievalHit] = []
        for chunk, raw_score in zip(chunks, raw_scores):
            hits.append(
                RetrievalHit(
                    source_type="material",
                    source_id=int(chunk.material_id),
                    title=chunk.material_title,
                    excerpt=chunk.text,
                    score=raw_score / max_raw_score,
                    metadata={
                        "material_id": int(chunk.material_id),
                        "chunk_index": int(chunk.chunk_index),
                        "source": chunk.source,
                        "backend": chunk.backend,
                        "backend_scores": dict(chunk.backend_scores),
                        "backend_ranks": dict(chunk.backend_ranks),
                        "raw_backend_score": raw_score,
                        "score_normalization": "per_query_max",
                        "file_type": chunk.file_type,
                        "project_id": chunk.project_id,
                    },
                )
            )
        return hits

    async def _search_context_store(
        self, query: str, user_id: int, source_type: str, limit: int
    ) -> list[RetrievalHit]:
        items = await self.context_store.retrieve(
            self.db,
            user_id,
            query,
            top_k=limit,
            source_types=(source_type,),
        )
        return [_context_item_to_hit(item) for item in items if item.source_type == source_type]

    async def _search_memories(self, query: str, user_id: int, limit: int) -> list[RetrievalHit]:
        terms = _query_terms(query)
        stmt = select(UserMemory).where(
            UserMemory.user_id == user_id,
            UserMemory.status == "active",
            UserMemory.review_status == CONFIRMED_REVIEW_STATUS,
            or_(UserMemory.expires_at.is_(None), UserMemory.expires_at > datetime.utcnow()),
        )
        if terms:
            clauses = []
            for term in terms[:12]:
                like = f"%{term}%"
                clauses.extend(
                    [
                        UserMemory.memory_key.ilike(like),
                        UserMemory.memory_value.ilike(like),
                        UserMemory.category.ilike(like),
                    ]
                )
            stmt = stmt.where(or_(*clauses))
        result = await self.db.execute(
            stmt.order_by(UserMemory.last_seen_at.desc(), UserMemory.id.desc()).limit(max(limit * 6, 40))
        )
        hits: list[RetrievalHit] = []
        for memory in result.scalars().all():
            score = _text_score(
                query,
                str(memory.memory_key or ""),
                str(memory.memory_value or ""),
                str(memory.category or ""),
            ) + float(memory.confidence or 0.0) * 0.25
            if terms and score <= 0:
                continue
            hits.append(
                RetrievalHit(
                    source_type="memory",
                    source_id=int(memory.id),
                    title=str(memory.memory_key or ""),
                    excerpt=str(memory.memory_value or "")[:400],
                    score=score,
                    metadata={
                        "source": f"memory:{memory.id}",
                        "category": memory.category,
                        "confidence": memory.confidence,
                        "locked": bool(memory.is_locked),
                        "review_status": memory.review_status,
                        "retrieval_backend": "confirmed_memory_sql",
                    },
                )
            )
        hits.sort(key=lambda item: (-item.score, -int(item.source_id)))
        return hits[:limit]

    async def _search_concepts(self, query: str, user_id: int, limit: int) -> list[RetrievalHit]:
        terms = _query_terms(query)
        stmt = select(Concept).where(Concept.user_id == user_id)
        if terms:
            clauses = []
            for term in terms[:12]:
                like = f"%{term}%"
                clauses.extend([Concept.name.ilike(like), Concept.description.ilike(like)])
            stmt = stmt.where(or_(*clauses))
        result = await self.db.execute(
            stmt.order_by(Concept.updated_at.desc(), Concept.id.desc()).limit(max(limit * 5, 30))
        )
        concepts = list(result.scalars().all())
        ranked = sorted(
            concepts,
            key=lambda concept: (
                -_text_score(query, str(concept.name or ""), str(concept.description or "")),
                -int(concept.id),
            ),
        )[:limit]
        if not ranked:
            return []

        selected_ids = [int(concept.id) for concept in ranked]
        edge_result = await self.db.execute(
            select(ConceptEdge).where(
                ConceptEdge.user_id == user_id,
                or_(
                    ConceptEdge.from_concept_id.in_(selected_ids),
                    ConceptEdge.to_concept_id.in_(selected_ids),
                ),
            )
        )
        edges = list(edge_result.scalars().all())
        neighbor_ids = {int(edge.from_concept_id) for edge in edges} | {
            int(edge.to_concept_id) for edge in edges
        }
        neighbor_result = await self.db.execute(
            select(Concept).where(Concept.user_id == user_id, Concept.id.in_(neighbor_ids or {-1}))
        )
        names = {int(item.id): str(item.name or "") for item in neighbor_result.scalars().all()}
        edges_by_concept: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for edge in edges:
            from_id = int(edge.from_concept_id)
            to_id = int(edge.to_concept_id)
            if from_id not in names or to_id not in names:
                continue
            payload = {
                "from_concept_id": from_id,
                "from_name": names[from_id],
                "to_concept_id": to_id,
                "to_name": names[to_id],
                "edge_type": edge.edge_type,
                "confidence": edge.confidence,
            }
            edges_by_concept[from_id].append(payload)
            edges_by_concept[to_id].append(payload)

        return [
            RetrievalHit(
                source_type="concept",
                source_id=int(concept.id),
                title=str(concept.name or ""),
                excerpt=str(concept.description or "")[:400],
                score=_text_score(query, str(concept.name or ""), str(concept.description or "")),
                metadata={
                    "source": f"concept:{concept.id}",
                    "concept_source": concept.source,
                    "edges": edges_by_concept.get(int(concept.id), [])[:12],
                    "retrieval_backend": "concept_graph_sql",
                },
            )
            for concept in ranked
        ]

    async def _search_learner_state(
        self, query: str, user_id: int, limit: int
    ) -> list[RetrievalHit]:
        terms = _query_terms(query)
        stmt = (
            select(UserConceptState, Concept)
            .join(Concept, Concept.id == UserConceptState.concept_id)
            .where(UserConceptState.user_id == user_id, Concept.user_id == user_id)
        )
        if terms:
            clauses = []
            for term in terms[:12]:
                like = f"%{term}%"
                clauses.extend([Concept.name.ilike(like), Concept.description.ilike(like)])
            stmt = stmt.where(or_(*clauses))
        result = await self.db.execute(stmt.limit(max(limit * 5, 30)))
        hits: list[RetrievalHit] = []
        for state, concept in result.all():
            text_score = _text_score(query, str(concept.name or ""), str(concept.description or ""))
            state_priority = float(state.forgetting_risk or 0.0) + (
                100.0 - float(state.mastery_estimate or 0.0)
            ) / 100.0
            score = text_score + state_priority * 0.35
            summary = (
                f"掌握度 {float(state.mastery_estimate or 0.0):.1f}，"
                f"置信度 {float(state.confidence or 0.0):.2f}，"
                f"遗忘风险 {float(state.forgetting_risk or 0.0):.2f}"
            )
            if state.common_error_type:
                summary += f"，常见错误：{state.common_error_type}"
            hits.append(
                RetrievalHit(
                    source_type="learner_state",
                    source_id=int(concept.id),
                    title=str(concept.name or ""),
                    excerpt=summary,
                    score=score,
                    metadata={
                        "source": f"learner_state:{concept.id}",
                        "concept_id": int(concept.id),
                        "mastery_estimate": state.mastery_estimate,
                        "confidence": state.confidence,
                        "forgetting_risk": state.forgetting_risk,
                        "common_error_type": state.common_error_type,
                        "next_review_at": state.next_review_at,
                        "last_reviewed_at": state.last_reviewed_at,
                        "reliability": state.reliability,
                        "model_version": state.model_version,
                        "retrieval_backend": "learner_state_sql",
                    },
                )
            )
        hits.sort(key=lambda item: (-item.score, int(item.source_id)))
        return hits[:limit]

    def _rrf_fuse(
        self, results: dict[str, list[RetrievalHit]], top_k: int
    ) -> list[RetrievalHit]:
        fused_scores: dict[str, float] = defaultdict(float)
        fused: dict[str, RetrievalHit] = {}
        source_scores: dict[str, dict[str, float]] = defaultdict(dict)
        source_ranks: dict[str, dict[str, int]] = defaultdict(dict)
        for source, hits in results.items():
            seen: set[str] = set()
            for rank, hit in enumerate(hits, start=1):
                if hit.key in seen:
                    continue
                seen.add(hit.key)
                fused_scores[hit.key] += 1.0 / (self.rrf_k + rank)
                source_scores[hit.key][source] = float(hit.score)
                source_ranks[hit.key][source] = rank
                fused.setdefault(hit.key, hit)
        if not fused:
            return []
        maximum = max(fused_scores.values()) or 1.0
        ranked: list[RetrievalHit] = []
        for key, hit in fused.items():
            metadata = dict(hit.metadata)
            metadata.update(
                {
                    "original_score": hit.score,
                    "rrf_score": fused_scores[key],
                    "source_scores": source_scores[key],
                    "source_ranks": source_ranks[key],
                }
            )
            ranked.append(replace(hit, score=fused_scores[key] / maximum, metadata=metadata))
        ranked.sort(key=lambda item: (-item.score, item.source_type, str(item.source_id)))
        return ranked[:top_k]

    async def load_hit(self, hit: RetrievalHit, *, user_id: int, level: int) -> str:
        level = max(L0, min(int(level), L2))
        if level <= L0:
            return hit.title
        if level == L1:
            return hit.excerpt
        if hit.source_type == "material":
            material_id = int(hit.metadata.get("material_id", hit.source_id))
            result = await self.db.execute(
                select(Material).where(Material.id == material_id, Material.user_id == user_id)
            )
            material = result.scalar_one_or_none()
            return str(material.content or "") if material else ""
        if hit.source_type == "note":
            return await self.context_store.load_tiered(
                self.db, user_id, "note", int(hit.source_id), L2
            )
        if hit.source_type == "memory":
            result = await self.db.execute(
                select(UserMemory).where(
                    UserMemory.id == int(hit.source_id),
                    UserMemory.user_id == user_id,
                    UserMemory.status == "active",
                    UserMemory.review_status == CONFIRMED_REVIEW_STATUS,
                )
            )
            memory = result.scalar_one_or_none()
            return str(memory.memory_value or "") if memory else ""
        if hit.source_type == "concept":
            result = await self.db.execute(
                select(Concept).where(Concept.id == int(hit.source_id), Concept.user_id == user_id)
            )
            concept = result.scalar_one_or_none()
            if not concept:
                return ""
            edges = hit.metadata.get("edges") or []
            relation_text = "；".join(
                f"{edge.get('from_name')} -{edge.get('edge_type')}-> {edge.get('to_name')}"
                for edge in edges
            )
            return "\n".join(part for part in [str(concept.description or ""), relation_text] if part)
        if hit.source_type == "learner_state":
            serializable = {
                key: value.isoformat() if hasattr(value, "isoformat") else value
                for key, value in hit.metadata.items()
                if key not in {"source", "retrieval_backend"}
            }
            return json.dumps(serializable, ensure_ascii=False, default=str)
        return ""


async def search_retrieval_context(
    db: AsyncSession,
    *,
    user_id: int,
    query: str,
    source_types: Sequence[str] = ROUTER_SOURCE_TYPES,
    top_k: int = 8,
    **scope: Any,
) -> list[RetrievalHit]:
    """Functional facade for callers that do not need router customization."""
    return await RetrievalRouter(db).search(
        query,
        user_id=user_id,
        source_types=source_types,
        top_k=top_k,
        **scope,
    )
