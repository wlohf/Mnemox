"""Optional, offline-only Qdrant Local comparison behind the material contract.

Qdrant is intentionally not imported at module load and is not a production
dependency. This adapter exists solely to produce an honest go/no-go spike.
"""
from __future__ import annotations

import asyncio
import hashlib
import math
import uuid
from collections import Counter
from typing import Any, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.material import Material
from app.services.material_retrieval_backend import (
    MaterialChunkHit,
    MaterialSearchScope,
    _chunk_material_text,
    _tokenize,
    resolve_material_ids,
)


def _sparse_index(token: str) -> int:
    return int.from_bytes(hashlib.blake2s(token.encode("utf-8"), digest_size=4).digest(), "big")


class QdrantMaterialRetrievalSpike:
    """Qdrant Local dense + sparse + RRF, with optional lexical reranking."""

    name = "qdrant"

    def __init__(
        self,
        db: AsyncSession,
        *,
        embedding_model: Any | None,
        dimension: int = 64,
        rerank: bool = False,
        client: Any | None = None,
        collection_name: str = "mnemox_retrieval_spike",
    ) -> None:
        try:
            from qdrant_client import QdrantClient, models
        except ImportError as exc:
            raise RuntimeError(
                "Qdrant spike is optional; install backend/requirements-spike.txt first."
            ) from exc

        self.db = db
        self.models = models
        self.embedding_model = embedding_model
        self.dimension = int(dimension)
        self.rerank = bool(rerank)
        self.name = "qdrant_rerank" if self.rerank else "qdrant"
        self.collection_name = collection_name
        self.client = client or QdrantClient(location=":memory:")
        if not self.client.collection_exists(collection_name):
            self.client.create_collection(
                collection_name=collection_name,
                vectors_config={
                    "dense": models.VectorParams(size=self.dimension, distance=models.Distance.COSINE)
                },
                sparse_vectors_config={
                    "sparse": models.SparseVectorParams(modifier=models.Modifier.IDF)
                },
            )

    def _sparse(self, text: str):
        counts = Counter(_tokenize(text))
        weighted: dict[int, float] = {}
        for token, count in counts.items():
            index = _sparse_index(token)
            weighted[index] = weighted.get(index, 0.0) + 1.0 + math.log(float(count))
        indices = sorted(weighted)
        return self.models.SparseVector(indices=indices, values=[weighted[index] for index in indices])

    def _scope_filter(self, scope: MaterialSearchScope, material_ids: Sequence[int]):
        clauses = [
            self.models.FieldCondition(
                key="user_id", match=self.models.MatchValue(value=int(scope.user_id))
            ),
            self.models.FieldCondition(
                key="material_id", match=self.models.MatchAny(any=[int(item) for item in material_ids])
            ),
        ]
        if scope.project_id is not None:
            clauses.append(
                self.models.FieldCondition(
                    key="project_ids", match=self.models.MatchValue(value=int(scope.project_id))
                )
            )
        return self.models.Filter(must=clauses)

    async def index_material(
        self,
        material: Material,
        *,
        user_id: int,
        project_ids: Sequence[int] = (),
    ) -> int:
        if int(material.user_id) != int(user_id):
            raise PermissionError("Cannot index another user's material")
        await self.remove_material(int(material.id), user_id=int(user_id))
        chunks = _chunk_material_text(str(material.content or ""))
        points = []
        for index, text in enumerate(chunks):
            vectors: dict[str, Any] = {"sparse": self._sparse(text)}
            if self.embedding_model is not None:
                vectors["dense"] = self.embedding_model.get_text_embedding(text)
            points.append(
                self.models.PointStruct(
                    id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"mnemox:{user_id}:{material.id}:{index}")),
                    vector=vectors,
                    payload={
                        "user_id": int(user_id),
                        "material_id": int(material.id),
                        "material_title": str(material.title or ""),
                        "file_type": str(material.file_type or ""),
                        "chunk_index": index,
                        "project_ids": [int(value) for value in project_ids],
                        "text": text,
                    },
                )
            )
        if points:
            await asyncio.to_thread(
                self.client.upsert,
                collection_name=self.collection_name,
                points=points,
            )
        return len(points)

    async def remove_material(self, material_id: int, *, user_id: int) -> None:
        filter_ = self.models.Filter(
            must=[
                self.models.FieldCondition(
                    key="user_id", match=self.models.MatchValue(value=int(user_id))
                ),
                self.models.FieldCondition(
                    key="material_id", match=self.models.MatchValue(value=int(material_id))
                ),
            ]
        )
        await asyncio.to_thread(
            self.client.delete,
            collection_name=self.collection_name,
            points_selector=self.models.FilterSelector(filter=filter_),
        )

    async def rebuild_user(self, user_id: int) -> int:
        filter_ = self.models.Filter(
            must=[
                self.models.FieldCondition(
                    key="user_id", match=self.models.MatchValue(value=int(user_id))
                )
            ]
        )
        await asyncio.to_thread(
            self.client.delete,
            collection_name=self.collection_name,
            points_selector=self.models.FilterSelector(filter=filter_),
        )
        rows = await self.db.scalars(
            select(Material).where(Material.user_id == int(user_id), Material.content.is_not(None))
        )
        total = 0
        for material in rows.all():
            total += await self.index_material(material, user_id=int(user_id))
        return total

    def _rerank_score(self, query: str, hit: MaterialChunkHit) -> float:
        terms = set(_tokenize(query))
        body = set(_tokenize(hit.text))
        title = set(_tokenize(hit.material_title))
        if not terms:
            return float(hit.score)
        coverage = len(terms & body) / len(terms)
        title_coverage = len(terms & title) / len(terms)
        exact = 1.0 if query.lower().strip() in hit.text.lower() else 0.0
        return coverage + 0.35 * title_coverage + 0.2 * exact + 0.05 * float(hit.score)

    async def search(
        self,
        query: str,
        *,
        scope: MaterialSearchScope,
        top_k: int = 8,
    ) -> list[MaterialChunkHit]:
        if not query.strip() or int(top_k) <= 0:
            return []
        material_ids = await resolve_material_ids(self.db, scope)
        if not material_ids:
            return []
        sparse = self._sparse(query)
        if not sparse.indices:
            return []
        scope_filter = self._scope_filter(scope, material_ids)
        candidate_limit = max(int(top_k) * 3, 8)
        kwargs: dict[str, Any] = {
            "collection_name": self.collection_name,
            "query_filter": scope_filter,
            "with_payload": True,
            "limit": candidate_limit,
        }
        if self.embedding_model is None:
            kwargs.update({"query": sparse, "using": "sparse"})
        else:
            dense = self.embedding_model.get_text_embedding(query)
            kwargs.update(
                {
                    "prefetch": [
                        self.models.Prefetch(query=dense, using="dense", filter=scope_filter, limit=candidate_limit),
                        self.models.Prefetch(query=sparse, using="sparse", filter=scope_filter, limit=candidate_limit),
                    ],
                    "query": self.models.FusionQuery(fusion=self.models.Fusion.RRF),
                }
            )
        response = await asyncio.to_thread(self.client.query_points, **kwargs)
        hits = []
        for point in response.points:
            payload = point.payload or {}
            material_id = int(payload.get("material_id") or 0)
            chunk_index = int(payload.get("chunk_index") or 0)
            hit = MaterialChunkHit(
                text=str(payload.get("text") or ""),
                score=float(point.score),
                material_id=material_id,
                material_title=str(payload.get("material_title") or ""),
                chunk_index=chunk_index,
                source=f"material:{material_id}#chunk:{chunk_index}",
                backend=self.name,
                file_type=str(payload.get("file_type") or ""),
                backend_scores={self.name: float(point.score)},
            )
            if self.rerank:
                hit.score = self._rerank_score(query, hit)
                hit.backend_scores["lexical_rerank"] = hit.score
            hits.append(hit)
        if self.rerank:
            hits.sort(key=lambda item: (-item.score, item.material_id, item.chunk_index))
        return hits[: int(top_k)]
