"""Replaceable retrieval backends for large learning materials.

This module is deliberately independent from the unified RetrievalRouter so it can
be plugged into the router without making the router depend on Chroma internals.
The legacy :mod:`app.ai.rag_service` remains the owner of embedding/index writes;
only this adapter knows how to read its existing Chroma collection.
"""
from __future__ import annotations

import asyncio
import hashlib
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Protocol, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.rag_service import RAGService, get_rag_service, load_rag_settings
from app.config import settings
from app.models.chat import ChatProject, ChatProjectMaterial
from app.models.material import Material


@dataclass(frozen=True)
class MaterialSearchScope:
    """Database-backed scope for material retrieval.

    Numeric material ranges are resolved in SQL first instead of being compared in
    Chroma metadata, where material IDs are stored as strings.
    """

    user_id: int
    material_ids: Optional[Sequence[int]] = None
    material_id_min: Optional[int] = None
    material_id_max: Optional[int] = None
    project_id: Optional[int] = None


@dataclass
class MaterialChunkHit:
    text: str
    score: float
    material_id: int
    material_title: str
    chunk_index: int
    source: str
    backend: str
    file_type: str = ""
    project_id: Optional[int] = None
    backend_scores: Dict[str, float] = field(default_factory=dict)
    backend_ranks: Dict[str, int] = field(default_factory=dict)

    @property
    def chunk_key(self) -> str:
        digest = hashlib.sha256(self.text.strip().encode("utf-8")).hexdigest()[:16]
        return f"material:{self.material_id}:chunk:{digest}"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "text": self.text,
            "score": round(float(self.score), 6),
            "material_id": self.material_id,
            "material_title": self.material_title,
            "chunk_index": self.chunk_index,
            "source": self.source,
            "backend": self.backend,
            "file_type": self.file_type,
            "project_id": self.project_id,
            "backend_scores": dict(self.backend_scores),
            "backend_ranks": dict(self.backend_ranks),
        }


class MaterialRetrievalBackend(Protocol):
    async def search(
        self,
        query: str,
        *,
        scope: MaterialSearchScope,
        top_k: int = 8,
    ) -> List[MaterialChunkHit]: ...


async def resolve_material_ids(db: AsyncSession, scope: MaterialSearchScope) -> List[int]:
    """Resolve explicit IDs/ranges/project scope with user isolation in SQL."""
    query = select(Material.id).where(Material.user_id == scope.user_id)

    if scope.material_ids is not None:
        explicit = sorted({int(item) for item in scope.material_ids})
        if not explicit:
            return []
        query = query.where(Material.id.in_(explicit))
    if scope.material_id_min is not None:
        query = query.where(Material.id >= int(scope.material_id_min))
    if scope.material_id_max is not None:
        query = query.where(Material.id <= int(scope.material_id_max))
    if scope.project_id is not None:
        query = (
            query.join(ChatProjectMaterial, ChatProjectMaterial.material_id == Material.id)
            .join(ChatProject, ChatProject.id == ChatProjectMaterial.project_id)
            .where(
                ChatProjectMaterial.project_id == int(scope.project_id),
                ChatProject.user_id == scope.user_id,
            )
        )

    result = await db.execute(query.order_by(Material.id))
    return [int(row[0]) for row in result.all()]


def _where_for_chroma(user_id: int, material_ids: Sequence[int]):
    filters: List[Dict[str, Any]] = [{"user_id": str(user_id)}]
    string_ids = [str(item) for item in material_ids]
    if len(string_ids) == 1:
        filters.append({"material_id": string_ids[0]})
    elif string_ids:
        filters.append({"material_id": {"$in": string_ids}})
    else:
        return None
    return {"$and": filters}


class ChromaMaterialRetrievalBackend:
    """Semantic backend over the existing Chroma material collection."""

    name = "chroma"

    def __init__(self, db: AsyncSession, rag: Optional[RAGService] = None) -> None:
        self.db = db
        self.rag = rag or get_rag_service()

    async def search(
        self,
        query: str,
        *,
        scope: MaterialSearchScope,
        top_k: int = 8,
    ) -> List[MaterialChunkHit]:
        if not query.strip() or top_k <= 0:
            return []

        await self.rag.initialize()
        if self.rag._embed_model is None:  # Legacy seam: isolated to this adapter.
            return []

        material_ids = await resolve_material_ids(self.db, scope)
        if not material_ids:
            return []

        where_filter = _where_for_chroma(scope.user_id, material_ids)
        threshold = float(
            getattr(self.rag, "_similarity_threshold", settings.RAG_SIMILARITY_THRESHOLD)
        )
        requested = max(int(top_k), 1)

        def _retrieve() -> List[MaterialChunkHit]:
            query_embedding = self.rag._embed_model.get_text_embedding(query)
            results = self.rag._collection.query(
                query_embeddings=[query_embedding],
                n_results=requested,
                where=where_filter,
                include=["documents", "metadatas", "distances"],
            )
            if not results or not results.get("documents") or not results["documents"][0]:
                return []

            docs = results["documents"][0]
            metas = results.get("metadatas", [[]])[0] or [{}] * len(docs)
            dists = results.get("distances", [[]])[0] or [1.0] * len(docs)
            hits: List[MaterialChunkHit] = []
            for doc, meta, dist in zip(docs, metas, dists):
                semantic_score = 1.0 - float(dist) / 2.0
                if semantic_score < threshold:
                    continue
                material_id = int(meta.get("material_id", 0) or 0)
                chunk_index = int(meta.get("chunk_index", 0) or 0)
                project_raw = meta.get("project_id")
                project_id = int(project_raw) if str(project_raw or "").isdigit() else None
                hits.append(
                    MaterialChunkHit(
                        text=str(doc or ""),
                        score=semantic_score,
                        material_id=material_id,
                        material_title=str(meta.get("title", "") or ""),
                        chunk_index=chunk_index,
                        source=f"material:{material_id}#chunk:{chunk_index}",
                        backend=self.name,
                        file_type=str(meta.get("file_type", "") or ""),
                        project_id=project_id,
                        backend_scores={self.name: semantic_score},
                    )
                )
            return hits

        try:
            return await asyncio.to_thread(_retrieve)
        except Exception:
            # RetrievalRouter owns partial-degradation policy; a backend failure must
            # therefore be representable as an empty candidate list.
            return []


def _tokenize(text: str) -> List[str]:
    """Dependency-free mixed Chinese/Latin tokens for the sparse fallback."""
    lowered = (text or "").lower()
    tokens = re.findall(r"[a-z0-9_]+|[\u4e00-\u9fff]+", lowered)
    expanded: List[str] = []
    for token in tokens:
        if re.fullmatch(r"[\u4e00-\u9fff]+", token):
            if len(token) <= 2:
                expanded.append(token)
            else:
                expanded.extend(token[index:index + 2] for index in range(len(token) - 1))
                expanded.append(token)
        else:
            expanded.append(token)
    return expanded


def _chunk_material_text(content: str) -> List[str]:
    """Use the same SentenceSplitter settings as Chroma indexing when possible."""
    if not content:
        return []
    cfg = load_rag_settings()
    chunk_size = int(cfg.get("chunk_size") or settings.RAG_CHUNK_SIZE)
    chunk_overlap = int(cfg.get("chunk_overlap") or settings.RAG_CHUNK_OVERLAP)
    try:
        from llama_index.core import Document
        from llama_index.core.node_parser import SentenceSplitter

        splitter = SentenceSplitter(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
        nodes = splitter.get_nodes_from_documents([Document(text=content)])
        return [node.get_content() for node in nodes if node.get_content().strip()]
    except Exception:
        # Keep keyword retrieval usable even when optional LlamaIndex components are
        # unavailable. Character windows are only a degradation path.
        size = max(256, chunk_size * 2)
        overlap = min(max(0, chunk_overlap * 2), size // 2)
        step = max(1, size - overlap)
        return [content[start:start + size] for start in range(0, len(content), step) if content[start:start + size].strip()]


class KeywordMaterialRetrievalBackend:
    """Small dependency-free BM25 backend over scoped material chunks."""

    name = "keyword"

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def search(
        self,
        query: str,
        *,
        scope: MaterialSearchScope,
        top_k: int = 8,
    ) -> List[MaterialChunkHit]:
        query_tokens = _tokenize(query)
        if not query_tokens or top_k <= 0:
            return []

        material_ids = await resolve_material_ids(self.db, scope)
        if not material_ids:
            return []
        result = await self.db.execute(
            select(Material).where(
                Material.user_id == scope.user_id,
                Material.id.in_(material_ids),
                Material.content.is_not(None),
            )
        )
        materials = list(result.scalars().all())

        docs: List[tuple[Material, int, str, List[str]]] = []
        document_frequency: Counter[str] = Counter()
        for material in materials:
            for chunk_index, chunk in enumerate(_chunk_material_text(material.content or "")):
                tokens = _tokenize(chunk)
                if not tokens:
                    continue
                docs.append((material, chunk_index, chunk, tokens))
                document_frequency.update(set(tokens))

        if not docs:
            return []
        avg_len = sum(len(item[3]) for item in docs) / len(docs)
        corpus_size = len(docs)
        query_counts = Counter(query_tokens)
        k1 = 1.5
        b = 0.75
        scored: List[MaterialChunkHit] = []

        for material, chunk_index, chunk, tokens in docs:
            tf = Counter(tokens)
            doc_len = len(tokens)
            score = 0.0
            for term, query_weight in query_counts.items():
                freq = tf.get(term, 0)
                if not freq:
                    continue
                df = document_frequency.get(term, 0)
                idf = math.log(1.0 + (corpus_size - df + 0.5) / (df + 0.5))
                norm = freq + k1 * (1.0 - b + b * doc_len / max(avg_len, 1.0))
                score += query_weight * idf * (freq * (k1 + 1.0) / norm)
            if score <= 0:
                continue
            scored.append(
                MaterialChunkHit(
                    text=chunk,
                    score=score,
                    material_id=int(material.id),
                    material_title=str(material.title or ""),
                    chunk_index=chunk_index,
                    source=f"material:{material.id}#chunk:{chunk_index}",
                    backend=self.name,
                    file_type=str(material.file_type or ""),
                    backend_scores={self.name: score},
                )
            )

        scored.sort(key=lambda item: (-item.score, item.material_id, item.chunk_index))
        return scored[: int(top_k)]


class HybridMaterialRetrievalBackend:
    """RRF fusion of replaceable semantic and keyword backends."""

    name = "hybrid"

    def __init__(
        self,
        semantic: MaterialRetrievalBackend,
        keyword: MaterialRetrievalBackend,
        *,
        rrf_k: int = 60,
    ) -> None:
        self.semantic = semantic
        self.keyword = keyword
        self.rrf_k = max(1, int(rrf_k))

    async def search(
        self,
        query: str,
        *,
        scope: MaterialSearchScope,
        top_k: int = 8,
    ) -> List[MaterialChunkHit]:
        candidate_k = max(int(top_k) * 3, int(top_k), 8)
        semantic_hits, keyword_hits = await asyncio.gather(
            self.semantic.search(query, scope=scope, top_k=candidate_k),
            self.keyword.search(query, scope=scope, top_k=candidate_k),
        )

        fused: Dict[str, MaterialChunkHit] = {}
        fused_scores: Dict[str, float] = defaultdict(float)
        for backend_name, hits in (("chroma", semantic_hits), ("keyword", keyword_hits)):
            for rank, hit in enumerate(hits, start=1):
                key = hit.chunk_key
                fused_scores[key] += 1.0 / (self.rrf_k + rank)
                if key not in fused:
                    fused[key] = MaterialChunkHit(**{**hit.__dict__})
                target = fused[key]
                target.backend_scores.update(hit.backend_scores or {backend_name: hit.score})
                target.backend_ranks[backend_name] = rank

        for key, hit in fused.items():
            hit.score = fused_scores[key]
            hit.backend = self.name
        ranked = sorted(
            fused.values(),
            key=lambda item: (-item.score, item.material_id, item.chunk_index),
        )
        return ranked[: max(0, int(top_k))]


def create_material_retrieval_backend(
    db: AsyncSession,
    *,
    mode: str = "hybrid",
    rag: Optional[RAGService] = None,
) -> MaterialRetrievalBackend:
    """Factory kept intentionally small so Qdrant/FTS backends can replace parts."""
    normalized = (mode or "hybrid").strip().lower()
    semantic = ChromaMaterialRetrievalBackend(db, rag=rag)
    keyword = KeywordMaterialRetrievalBackend(db)
    if normalized in {"chroma", "semantic"}:
        return semantic
    if normalized in {"keyword", "bm25", "sparse"}:
        return keyword
    if normalized == "hybrid":
        return HybridMaterialRetrievalBackend(semantic, keyword)
    raise ValueError(f"Unsupported material retrieval backend: {mode}")


class MaterialIndexRebuilder:
    """User-scoped one-click Chroma rebuild without clearing other users' chunks."""

    def __init__(self, db: AsyncSession, rag: Optional[RAGService] = None) -> None:
        self.db = db
        self.rag = rag or get_rag_service()

    async def _delete_user_chunks(self, user_id: int) -> None:
        await self.rag.initialize()

        def _delete() -> None:
            self.rag._collection.delete(where={"user_id": str(user_id)})

        await asyncio.to_thread(_delete)

    async def _project_ids(self, material_id: int, user_id: int) -> List[int]:
        result = await self.db.execute(
            select(ChatProjectMaterial.project_id)
            .join(ChatProject, ChatProject.id == ChatProjectMaterial.project_id)
            .where(
                ChatProject.user_id == user_id,
                ChatProjectMaterial.material_id == material_id,
            )
        )
        return [int(row[0]) for row in result.all()]

    async def rebuild_user(
        self,
        user_id: int,
        *,
        material_ids: Optional[Sequence[int]] = None,
    ) -> Dict[str, Any]:
        await self.rag.initialize()
        status = await self.rag.get_status(user_id)
        if not status.get("embedding_enabled"):
            return {
                "ok": False,
                "materials_total": 0,
                "materials_indexed": 0,
                "failed": 0,
                "total_chunks": 0,
                "message": "未配置 embedding API Key，已跳过向量索引。",
            }

        query = select(Material).where(Material.user_id == user_id, Material.content.is_not(None))
        explicit_ids = sorted({int(item) for item in material_ids or []})
        if material_ids is not None:
            if not explicit_ids:
                return {
                    "ok": True,
                    "materials_total": 0,
                    "materials_indexed": 0,
                    "failed": 0,
                    "total_chunks": 0,
                    "message": "没有需要重建的资料。",
                }
            query = query.where(Material.id.in_(explicit_ids))
        result = await self.db.execute(query.order_by(Material.id))
        materials = list(result.scalars().all())

        if material_ids is None:
            await self._delete_user_chunks(user_id)
        else:
            for material_id in explicit_ids:
                await self.rag.remove_material(material_id, user_id=user_id)

        indexed = 0
        total_chunks = 0
        failures: List[Dict[str, Any]] = []
        for material in materials:
            project_ids = await self._project_ids(int(material.id), user_id)
            count = await self.rag.index_material(
                material_id=int(material.id),
                title=str(material.title or ""),
                content=str(material.content or ""),
                file_type=material.file_type,
                project_ids=project_ids,
                user_id=user_id,
            )
            if count > 0:
                indexed += 1
                total_chunks += count
            else:
                failures.append({"material_id": int(material.id), "title": str(material.title or "")})

        return {
            "ok": not failures,
            "materials_total": len(materials),
            "materials_indexed": indexed,
            "failed": len(failures),
            "failures": failures,
            "total_chunks": total_chunks,
            "message": (
                f"已重建 {indexed}/{len(materials)} 份资料，共 {total_chunks} 个片段"
                if not failures
                else f"重建完成但有 {len(failures)} 份资料索引失败"
            ),
        }
