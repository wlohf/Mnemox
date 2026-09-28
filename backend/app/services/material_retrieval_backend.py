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
import sys
from collections import Counter, OrderedDict, defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.rag_service import RAGService, get_rag_service, load_rag_settings
from app.config import settings
from app.models.chat import ChatProject, ChatProjectMaterial
from app.models.material import Material, material_content_digest
from app.models.retrieval import RetrievalProjection, RetrievalProjectionChunk


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
        return f"material:{self.material_id}:chunk:{self.chunk_index}"

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
    if (
        scope.material_id_min is not None
        and scope.material_id_max is not None
        and int(scope.material_id_min) > int(scope.material_id_max)
    ):
        return []

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
    # Project scope is already resolved to material IDs in SQL; vectors carry
    # no project membership, so joining or leaving a project never re-embeds.
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
        if not settings.RAG_ENABLED:
            return []

        await self.rag.initialize()
        if self.rag._embed_model is None:  # Legacy seam: isolated to this adapter.
            return []
        if self.rag.vector_incompatible:
            return []

        material_ids = await resolve_material_ids(self.db, scope)
        if not material_ids:
            return []

        where_filter = _where_for_chroma(scope.user_id, material_ids)
        threshold = float(
            getattr(self.rag, "_similarity_threshold", settings.RAG_SIMILARITY_THRESHOLD)
        )
        # Indexes written before single-copy vectors hold the same chunk once per
        # project. Oversample before de-duplication so those copies do not crowd
        # distinct chunks out of the requested top-k window.
        requested = max(int(top_k) * 4, 1)

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
            seen_chunks: set[str] = set()
            for doc, meta, dist in zip(docs, metas, dists):
                semantic_score = 1.0 - float(dist) / 2.0
                if semantic_score < threshold:
                    continue
                material_id = int(meta.get("material_id", 0) or 0)
                chunk_index = int(meta.get("chunk_index", 0) or 0)
                project_raw = meta.get("project_id")
                project_id = int(project_raw) if str(project_raw or "").isdigit() else None
                hit = MaterialChunkHit(
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
                if hit.chunk_key in seen_chunks:
                    continue
                seen_chunks.add(hit.chunk_key)
                hits.append(hit)
                if len(hits) >= int(top_k):
                    break
            return hits

        try:
            hits = await asyncio.to_thread(_retrieve)
            # Validate after external I/O against a fresh SQL transaction. Legacy
            # vectors without a current manifest are excluded until rebuilt.
            if not hits:
                return []
            async with AsyncSession(bind=self.db.bind) as verify:
                rows = (await verify.execute(
                    select(
                        Material.id, Material.title, Material.file_type, Material.content_hash,
                        RetrievalProjection.content_hash,
                        RetrievalProjectionChunk.chunk_index, RetrievalProjectionChunk.chunk_hash,
                    )
                    .join(RetrievalProjection, (RetrievalProjection.source_id == Material.id)
                          & (RetrievalProjection.user_id == Material.user_id))
                    .join(RetrievalProjectionChunk, RetrievalProjectionChunk.projection_id == RetrievalProjection.id)
                    .where(Material.user_id == scope.user_id, Material.id.in_({hit.material_id for hit in hits}),
                        RetrievalProjection.source_type == "material", RetrievalProjection.status == "ready",
                        RetrievalProjection.indexed_version == RetrievalProjection.source_version,
                        RetrievalProjectionChunk.source_version == RetrievalProjection.source_version))).all()
                canonical_digests = {int(row[0]): row[3] for row in rows}
                projected_digests = {int(row[0]): row[4] for row in rows}
                current, _bodies = await _settle_projection_currency(
                    verify, scope.user_id, canonical_digests, projected_digests,
                )
                valid = {
                    (int(material_id), int(chunk_index)): (chunk_hash, title, file_type)
                    for material_id, title, file_type, _, _, chunk_index, chunk_hash in rows
                    if int(material_id) in current
                }
                safe_hits = []
                for hit in hits:
                    canonical = valid.get((hit.material_id, hit.chunk_index))
                    if canonical and hashlib.sha256(hit.text.encode()).hexdigest() == canonical[0]:
                        hit.material_title, hit.file_type = canonical[1], canonical[2] or ""
                        safe_hits.append(hit)
                return safe_hits
        except Exception as exc:
            if self.rag._looks_like_dimension_mismatch(exc):
                # The collection is shared: pause and let the lifecycle handler
                # reset it once, rather than wiping every user's vectors here.
                self.rag.mark_vector_incompatible(exc, user_id=scope.user_id)
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
        size = max(256, chunk_size * 2)
        overlap = min(max(0, chunk_overlap * 2), size // 2)
        step = max(1, size - overlap)
        return [
            content[start:start + size]
            for start in range(0, len(content), step)
            if content[start:start + size].strip()
        ]


async def _settle_projection_currency(
    db: AsyncSession,
    user_id: int,
    canonical_digests: Dict[int, Optional[str]],
    projected_digests: Dict[int, Optional[str]],
) -> tuple[set[int], Dict[int, str]]:
    """Return materials whose projection still matches canonical SQL text.

    ``Material.content_hash`` is refreshed on every ORM write of ``content``,
    so an equal digest vouches for the projection without reading the body.
    Any disagreement (legacy rows, missing projections) is settled against the
    canonical text; bodies read for materials that are not current are returned.
    """
    current = {
        material_id
        for material_id, digest in projected_digests.items()
        if digest is not None and canonical_digests.get(material_id) == digest
    }
    unsettled = [material_id for material_id in canonical_digests if material_id not in current]
    bodies: Dict[int, str] = {}
    if unsettled:
        result = await db.execute(
            select(Material.id, Material.content).where(
                Material.user_id == user_id,
                Material.id.in_(unsettled),
            )
        )
        for material_id, content in result.all():
            text = str(content or "")
            if projected_digests.get(int(material_id)) == material_content_digest(text):
                current.add(int(material_id))
            else:
                bodies[int(material_id)] = text
    return current, bodies


# Upper bound on cached (term, frequency) entries across all chunks; roughly
# 50-100 MB. Larger corpora stay correct but re-tokenize evicted chunks.
_TOKEN_CACHE_MAX_TERMS = 2_000_000
_CHUNK_TEXT_BATCH_SIZE = 500

ChunkTokenStats = tuple[Dict[str, int], int]


def _chunk_token_stats(text: str) -> ChunkTokenStats:
    tokens = _tokenize(text)
    return dict(Counter(sys.intern(token) for token in tokens)), len(tokens)


class _ChunkTokenCache:
    """LRU of per-chunk term frequencies keyed by the chunk's text digest.

    Keys are content addresses, so an entry can never describe stale text.
    """

    def __init__(self, max_terms: int) -> None:
        self.max_terms = max_terms
        self._entries: "OrderedDict[str, ChunkTokenStats]" = OrderedDict()
        self._terms = 0

    def get(self, digest: str) -> Optional[ChunkTokenStats]:
        entry = self._entries.get(digest)
        if entry is not None:
            self._entries.move_to_end(digest)
        return entry

    def put(self, digest: str, entry: ChunkTokenStats) -> None:
        if digest in self._entries:
            self._entries.move_to_end(digest)
            return
        self._entries[digest] = entry
        self._terms += len(entry[0])
        while self._terms > self.max_terms and len(self._entries) > 1:
            _, evicted = self._entries.popitem(last=False)
            self._terms -= len(evicted[0])


_chunk_token_cache = _ChunkTokenCache(_TOKEN_CACHE_MAX_TERMS)


class KeywordMaterialRetrievalBackend:
    """Dependency-free BM25 over the persisted chunk manifest.

    A query reads chunk metadata, tokenizes only chunks missing from the token
    cache, and loads text just for those and for the returned hits. Material
    bodies are read only when a manifest cannot be vouched for by its digest.
    """

    name = "keyword"

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def _chunk_texts(self, user_id: int, chunk_ids: Sequence[int]) -> Dict[int, str]:
        texts: Dict[int, str] = {}
        ids = list(chunk_ids)
        for start in range(0, len(ids), _CHUNK_TEXT_BATCH_SIZE):
            result = await self.db.execute(
                select(RetrievalProjectionChunk.id, RetrievalProjectionChunk.text).where(
                    RetrievalProjectionChunk.user_id == user_id,
                    RetrievalProjectionChunk.id.in_(ids[start:start + _CHUNK_TEXT_BATCH_SIZE]),
                )
            )
            texts.update({int(chunk_id): str(text or "") for chunk_id, text in result.all()})
        return texts

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
        heads = {
            int(row.id): row
            for row in (
                await self.db.execute(
                    select(Material.id, Material.title, Material.file_type, Material.content_hash).where(
                        Material.user_id == scope.user_id,
                        Material.id.in_(material_ids),
                        Material.content.is_not(None),
                    )
                )
            ).all()
        }
        if not heads:
            return []
        manifests_result = await self.db.execute(
            select(
                RetrievalProjectionChunk.id,
                RetrievalProjectionChunk.source_id,
                RetrievalProjectionChunk.chunk_index,
                RetrievalProjectionChunk.chunk_hash,
                RetrievalProjection.content_hash,
            )
            .join(
                RetrievalProjection,
                RetrievalProjection.id == RetrievalProjectionChunk.projection_id,
            )
            .where(
                RetrievalProjectionChunk.user_id == scope.user_id,
                RetrievalProjectionChunk.source_type == "material",
                RetrievalProjectionChunk.source_id.in_(list(heads)),
                RetrievalProjection.user_id == scope.user_id,
                RetrievalProjection.source_id == RetrievalProjectionChunk.source_id,
                RetrievalProjection.source_version == RetrievalProjectionChunk.source_version,
                RetrievalProjection.status.in_(("indexing", "ready", "degraded", "failed")),
                RetrievalProjection.last_operation != "forget",
            )
            .order_by(RetrievalProjectionChunk.source_id, RetrievalProjectionChunk.chunk_index)
        )
        persisted_chunks: Dict[int, List[tuple[int, int, str]]] = defaultdict(list)
        projected_digests: Dict[int, Optional[str]] = {}
        for chunk_id, source_id, chunk_index, chunk_hash, projected_hash in manifests_result.all():
            persisted_chunks[int(source_id)].append((int(chunk_id), int(chunk_index), str(chunk_hash)))
            projected_digests[int(source_id)] = projected_hash
        current, bodies = await _settle_projection_currency(
            self.db,
            scope.user_id,
            {material_id: head.content_hash for material_id, head in heads.items()},
            projected_digests,
        )

        # (material_id, chunk_index, chunk_id or None, text or None, stats)
        docs: List[tuple[int, int, Optional[int], Optional[str], ChunkTokenStats]] = []
        cached: Dict[str, ChunkTokenStats] = {}
        missing: Dict[int, str] = {}
        for material_id in current:
            for chunk_id, _chunk_index, chunk_hash in persisted_chunks.get(material_id, []):
                stats = cached.get(chunk_hash) or _chunk_token_cache.get(chunk_hash)
                if stats is None:
                    missing[chunk_id] = chunk_hash
                else:
                    cached[chunk_hash] = stats
        texts = await self._chunk_texts(scope.user_id, list(missing)) if missing else {}
        for chunk_id, text in texts.items():
            stats = _chunk_token_stats(text)
            digest = missing[chunk_id]
            cached[digest] = stats
            if hashlib.sha256(text.encode("utf-8")).hexdigest() == digest:
                _chunk_token_cache.put(digest, stats)
        for material_id in current:
            for chunk_id, chunk_index, chunk_hash in persisted_chunks.get(material_id, []):
                stats = cached.get(chunk_hash)
                if stats is not None and stats[1]:
                    docs.append((material_id, chunk_index, chunk_id, texts.get(chunk_id), stats))
        # Materials without a current manifest are chunked from canonical text.
        for material_id, body in bodies.items():
            for chunk_index, chunk in enumerate(_chunk_material_text(body)):
                stats = _chunk_token_stats(chunk)
                if stats[1]:
                    docs.append((material_id, chunk_index, None, chunk, stats))

        if not docs:
            return []
        corpus_size = len(docs)
        avg_len = sum(doc[4][1] for doc in docs) / corpus_size
        query_counts = Counter(query_tokens)
        query_terms = set(query_counts)
        document_frequency: Counter[str] = Counter()
        matching = []
        for doc in docs:
            common = query_terms.intersection(doc[4][0])
            if common:
                document_frequency.update(common)
                matching.append(doc)
        k1 = 1.5
        b = 0.75
        scored: List[tuple[float, int, int, Optional[int], Optional[str]]] = []

        for material_id, chunk_index, chunk_id, text, (tf, doc_len) in matching:
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
            scored.append((score, material_id, chunk_index, chunk_id, text))

        scored.sort(key=lambda item: (-item[0], item[1], item[2]))
        top = scored[: int(top_k)]
        unread = [chunk_id for _, _, _, chunk_id, text in top if text is None and chunk_id is not None]
        if unread:
            texts.update(await self._chunk_texts(scope.user_id, unread))

        hits: List[MaterialChunkHit] = []
        for score, material_id, chunk_index, chunk_id, text in top:
            if text is None:
                text = texts.get(chunk_id) if chunk_id is not None else None
                if text is None:
                    continue  # Replaced by a concurrent re-index; the next query sees it.
            head = heads[material_id]
            hits.append(
                MaterialChunkHit(
                    text=text,
                    score=score,
                    material_id=material_id,
                    material_title=str(head.title or ""),
                    chunk_index=chunk_index,
                    source=f"material:{material_id}#chunk:{chunk_index}",
                    backend=self.name,
                    file_type=str(head.file_type or ""),
                    backend_scores={self.name: score},
                )
            )
        return hits


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
        try:
            semantic_hits = await self.semantic.search(query, scope=scope, top_k=candidate_k)
        except Exception:
            semantic_hits = []
        try:
            keyword_hits = await self.keyword.search(query, scope=scope, top_k=candidate_k)
        except Exception:
            keyword_hits = []

        fused: Dict[str, MaterialChunkHit] = {}
        fused_scores: Dict[str, float] = defaultdict(float)
        for backend_name, hits in (("chroma", semantic_hits), ("keyword", keyword_hits)):
            seen_backend_keys: set[str] = set()
            for rank, hit in enumerate(hits, start=1):
                key = hit.chunk_key
                if key in seen_backend_keys:
                    continue
                seen_backend_keys.add(key)
                fused_scores[key] += 1.0 / (self.rrf_k + rank)
                if key not in fused:
                    fused[key] = MaterialChunkHit(
                        **{
                            **hit.__dict__,
                            "backend_scores": dict(hit.backend_scores),
                            "backend_ranks": dict(hit.backend_ranks),
                        }
                    )
                target = fused[key]
                if backend_name == "keyword" and target.text != hit.text:
                    # Different text at the same chunk offset is a different
                    # version: never give stale text a fresh keyword score.
                    target = MaterialChunkHit(**{**hit.__dict__, "backend_scores": {}, "backend_ranks": {}})
                    fused[key] = target
                    fused_scores[key] = 1.0 / (self.rrf_k + rank)
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
            count = await self.rag.index_material(
                material_id=int(material.id),
                title=str(material.title or ""),
                content=str(material.content or ""),
                file_type=material.file_type,
                user_id=user_id,
            )
            if count > 0:
                indexed += 1
                total_chunks += count
            else:
                failures.append({"material_id": int(material.id), "title": str(material.title or "")})

        last_error = ""
        if failures:
            current_status = await self.rag.get_status(user_id)
            last_error = str(current_status.get("last_error") or "")
        return {
            "ok": not failures,
            "materials_total": len(materials),
            "materials_indexed": indexed,
            "failed": len(failures),
            "failures": failures,
            "total_chunks": total_chunks,
            "last_error": last_error,
            "message": (
                f"已重建 {indexed}/{len(materials)} 份资料，共 {total_chunks} 个片段"
                if not failures
                else f"重建完成但有 {len(failures)} 份资料索引失败"
            ),
        }
