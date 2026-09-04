"""Disposable, user-scoped Chroma index for Stage 3 knowledge objects."""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

from app.ai.rag_service import create_embedding_model, load_rag_settings
from app.config import settings
from app.utils.outbound_url import validate_ai_provider_url
from app.utils.paths import get_chromadb_dir


class KnowledgeEmbeddingUnavailable(RuntimeError):
    """The optional knowledge vector projection cannot currently run."""


@dataclass(frozen=True)
class KnowledgeEmbeddingConfiguration:
    embedding_model: str
    base_url: str
    fingerprint: str
    collection: str
    enabled: bool


def knowledge_embedding_configuration() -> KnowledgeEmbeddingConfiguration:
    saved = load_rag_settings()
    api_key = str(saved.get("api_key") or settings.OPENAI_API_KEY or "")
    base_url = str(saved.get("base_url") or settings.OPENAI_BASE_URL or "").rstrip("/")
    model = str(saved.get("model") or settings.RAG_EMBEDDING_MODEL or "").strip()
    identity = json.dumps(
        {"base_url": base_url, "embedding_model": model},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    fingerprint = hashlib.sha256(identity.encode("utf-8")).hexdigest()
    base_name = re.sub(
        r"[^a-zA-Z0-9_-]+",
        "-",
        str(settings.KNOWLEDGE_CHROMA_COLLECTION_NAME or "mnemox_knowledge"),
    ).strip("-_") or "mnemox_knowledge"
    collection = f"{base_name[:140]}_{fingerprint[:12]}"
    return KnowledgeEmbeddingConfiguration(
        embedding_model=model[:160],
        base_url=base_url,
        fingerprint=fingerprint,
        collection=collection,
        enabled=bool(settings.KNOWLEDGE_EMBEDDING_ENABLED and api_key and model),
    )


class ChromaKnowledgeEmbeddingIndex:
    """Small adapter that never shares the ordinary Material collection."""

    def __init__(self) -> None:
        self._client = None
        self._collection = None
        self._embed_model = None
        self._configuration_fingerprint = ""

    def configuration(self) -> KnowledgeEmbeddingConfiguration:
        return knowledge_embedding_configuration()

    def _ensure_client(self):
        if self._client is None:
            import chromadb

            self._client = chromadb.PersistentClient(path=str(get_chromadb_dir()))
        return self._client

    async def _ensure_ready(self) -> KnowledgeEmbeddingConfiguration:
        config = self.configuration()
        saved = load_rag_settings()
        api_key = str(saved.get("api_key") or settings.OPENAI_API_KEY or "")
        if not settings.KNOWLEDGE_EMBEDDING_ENABLED:
            raise KnowledgeEmbeddingUnavailable("knowledge_embedding_disabled")
        if not api_key:
            raise KnowledgeEmbeddingUnavailable("knowledge_embedding_api_key_missing")
        if not config.embedding_model:
            raise KnowledgeEmbeddingUnavailable("knowledge_embedding_model_missing")
        base_url = await validate_ai_provider_url(config.base_url)
        if self._configuration_fingerprint != config.fingerprint:
            client = await asyncio.to_thread(self._ensure_client)

            def _initialize():
                collection = client.get_or_create_collection(
                    name=config.collection,
                    metadata={"hnsw:space": "cosine", "purpose": "mnemox_knowledge"},
                )
                model = create_embedding_model(
                    api_key=api_key,
                    base_url=base_url,
                    model=config.embedding_model,
                )
                return collection, model

            self._collection, self._embed_model = await asyncio.to_thread(_initialize)
            self._configuration_fingerprint = config.fingerprint
        return config

    async def upsert(
        self,
        *,
        vector_key: str,
        text: str,
        metadata: dict[str, Any],
    ) -> KnowledgeEmbeddingConfiguration:
        config = await self._ensure_ready()
        content = str(text or "").strip()
        if not content:
            raise ValueError("knowledge_embedding_text_empty")

        def _upsert() -> None:
            embedding = self._embed_model.get_text_embedding(content)
            safe_metadata = {
                str(key): value
                for key, value in metadata.items()
                if isinstance(value, (str, int, float, bool))
            }
            self._collection.upsert(
                ids=[str(vector_key)],
                documents=[content],
                metadatas=[safe_metadata],
                embeddings=[embedding],
            )

        await asyncio.wait_for(
            asyncio.to_thread(_upsert),
            timeout=float(settings.KNOWLEDGE_EMBEDDING_TIMEOUT_SECONDS),
        )
        return config

    async def delete(self, *, vector_key: str, collection: str) -> None:
        client = await asyncio.to_thread(self._ensure_client)

        def _delete() -> None:
            try:
                target = client.get_collection(name=str(collection))
            except Exception as exc:
                lowered = str(exc).casefold()
                if "not found" in lowered or "does not exist" in lowered:
                    return
                raise
            target.delete(ids=[str(vector_key)])

        await asyncio.to_thread(_delete)

    async def query_concepts(
        self,
        *,
        user_id: int,
        text: str,
        top_k: int,
    ) -> list[dict[str, Any]]:
        await self._ensure_ready()
        query_text = str(text or "").strip()
        if not query_text:
            return []

        def _query() -> list[dict[str, Any]]:
            embedding = self._embed_model.get_text_embedding(query_text)
            result = self._collection.query(
                query_embeddings=[embedding],
                n_results=max(1, min(50, int(top_k))),
                where={
                    "$and": [
                        {"user_id": str(int(user_id))},
                        {"object_type": "concept"},
                    ]
                },
                include=["metadatas", "distances"],
            )
            metadatas = (result.get("metadatas") or [[]])[0]
            distances = (result.get("distances") or [[]])[0]
            rows: list[dict[str, Any]] = []
            for metadata, distance in zip(metadatas, distances):
                concept_id = int((metadata or {}).get("object_id") or 0)
                if concept_id <= 0:
                    continue
                score = max(0.0, min(1.0, 1.0 - float(distance) / 2.0))
                rows.append({"concept_id": concept_id, "score": score})
            return rows

        return await asyncio.wait_for(
            asyncio.to_thread(_query),
            timeout=float(settings.KNOWLEDGE_EMBEDDING_TIMEOUT_SECONDS),
        )

    async def query_claims(
        self,
        *,
        user_id: int,
        text: str,
        top_k: int,
    ) -> list[dict[str, Any]]:
        """Query the disposable Claim projection; callers must revalidate in SQL."""
        await self._ensure_ready()
        query_text = str(text or "").strip()
        if not query_text:
            return []

        def _query() -> list[dict[str, Any]]:
            embedding = self._embed_model.get_text_embedding(query_text)
            result = self._collection.query(
                query_embeddings=[embedding],
                n_results=max(1, min(50, int(top_k))),
                where={"$and": [{"user_id": str(int(user_id))}, {"object_type": "claim"}]},
                include=["metadatas", "distances"],
            )
            rows: list[dict[str, Any]] = []
            for metadata, distance in zip(
                (result.get("metadatas") or [[]])[0],
                (result.get("distances") or [[]])[0],
            ):
                claim_id = int((metadata or {}).get("object_id") or 0)
                if claim_id > 0:
                    rows.append({
                        "claim_id": claim_id,
                        "score": max(0.0, min(1.0, 1.0 - float(distance) / 2.0)),
                    })
            return rows

        return await asyncio.wait_for(
            asyncio.to_thread(_query),
            timeout=float(settings.KNOWLEDGE_EMBEDDING_TIMEOUT_SECONDS),
        )


_knowledge_embedding_index: ChromaKnowledgeEmbeddingIndex | None = None


def get_knowledge_embedding_index() -> ChromaKnowledgeEmbeddingIndex:
    global _knowledge_embedding_index
    if _knowledge_embedding_index is None:
        _knowledge_embedding_index = ChromaKnowledgeEmbeddingIndex()
    return _knowledge_embedding_index
