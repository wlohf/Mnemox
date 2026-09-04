"""Recoverable material ingest, refresh, forget, and rebuild projections.

Canonical material text remains in SQL. The SQL chunk manifest and Chroma
vectors are disposable projections that can always be reconstructed from it.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from collections import Counter
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, AsyncIterator, Optional, Sequence

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.rag_service import RAGService, get_rag_service, load_rag_settings
from app.config import settings
from app.models.chat import ChatProject, ChatProjectMaterial
from app.models.material import Material
from app.models.retrieval import RetrievalProjection, RetrievalProjectionChunk
from app.services.material_retrieval_backend import _chunk_material_text
from app.utils.error_safety import (
    redact_sensitive_text,
    safe_error_diagnostic,
    safe_exception_summary,
)
from app.utils.operation_lock import serialized_global_operation, serialized_user_operation
from app.utils.utc import to_utc_iso, utc_now_db

logger = logging.getLogger(__name__)

PROJECTION_BACKEND = "chroma"
SOURCE_TYPE = "material"
MAX_ERROR_CHARS = 1000
RETRIEVAL_MUTATION_LOCK_NAMESPACE = "retrieval_projection_user_v1"
RETRIEVAL_CONFIGURATION_LOCK_NAMESPACE = "retrieval_projection_configuration_v1"


@asynccontextmanager
async def serialized_retrieval_mutation(
    db: AsyncSession,
    *,
    user_id: int,
) -> AsyncIterator[None]:
    """Keep each user mutation stable across a global configuration switch."""

    async with serialized_global_operation(
        db,
        namespace=RETRIEVAL_CONFIGURATION_LOCK_NAMESPACE,
        exclusive=False,
    ):
        async with serialized_user_operation(
            db,
            namespace=RETRIEVAL_MUTATION_LOCK_NAMESPACE,
            user_id=int(user_id),
        ):
            yield


@asynccontextmanager
async def serialized_retrieval_configuration_change(db: AsyncSession) -> AsyncIterator[None]:
    """Exclude every ingest/rebuild while changing global retrieval settings."""

    async with serialized_global_operation(
        db,
        namespace=RETRIEVAL_CONFIGURATION_LOCK_NAMESPACE,
        exclusive=True,
    ):
        yield


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _utcnow() -> datetime:
    return utc_now_db()


def _safe_error(value: Any) -> str:
    return redact_sensitive_text(value, max_chars=MAX_ERROR_CHARS)


def retrieval_configuration(rag: RAGService | None = None) -> dict[str, Any]:
    """Describe index compatibility without ever including an embedding key."""
    saved = load_rag_settings()
    model = str(
        getattr(rag, "_current_model", "")
        or saved.get("model")
        or settings.RAG_EMBEDDING_MODEL
    )
    chunk_size = int(
        getattr(rag, "_chunk_size", None)
        or saved.get("chunk_size")
        or settings.RAG_CHUNK_SIZE
    )
    chunk_overlap = int(
        getattr(rag, "_chunk_overlap", None)
        if getattr(rag, "_chunk_overlap", None) is not None
        else saved.get("chunk_overlap", settings.RAG_CHUNK_OVERLAP)
    )
    base_url = str(
        getattr(rag, "_current_base_url", "")
        or saved.get("base_url")
        or settings.OPENAI_BASE_URL
    ).rstrip("/")
    identity = {
        "backend": PROJECTION_BACKEND,
        "embedding_model": model,
        "embedding_base_url": base_url,
        "chunk_size": chunk_size,
        "chunk_overlap": chunk_overlap,
    }
    identity["fingerprint"] = _sha256(
        json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    )
    return identity


def serialize_projection(row: RetrievalProjection | None) -> dict[str, Any] | None:
    if row is None:
        return None
    # SQLAlchemy expires server-managed ``onupdate`` values after each flush.
    # Reading such a value synchronously from an AsyncSession causes
    # MissingGreenlet, so use its loaded snapshot until the next explicit read.
    updated_at = row.__dict__.get("updated_at")
    safe_last_error = _safe_error(row.last_error) if row.last_error else None
    error_code: str | None = None
    error_fingerprint: str | None = None
    if safe_last_error:
        if str(row.status) == "failed" and str(row.last_operation) == "forget":
            error_code = "retrieval.forget_failed"
        elif str(row.status) == "failed":
            error_code = "retrieval.index_failed"
        elif str(row.status) == "degraded":
            error_code = "retrieval.degraded"
        else:
            error_code = "retrieval.diagnostic"
        diagnostic = safe_error_diagnostic(
            safe_last_error,
            code=error_code,
            max_chars=MAX_ERROR_CHARS,
        )
        error_code = diagnostic.code
        error_fingerprint = diagnostic.fingerprint
    return {
        "source_type": str(row.source_type),
        "source_id": int(row.source_id),
        "backend": str(row.backend),
        "status": str(row.status),
        "operation": str(row.last_operation),
        "source_version": int(row.source_version),
        "indexed_version": int(row.indexed_version) if row.indexed_version is not None else None,
        "content_hash": row.content_hash,
        "configuration_fingerprint": row.configuration_fingerprint,
        "embedding_model": row.embedding_model,
        "chunk_size": row.chunk_size,
        "chunk_overlap": row.chunk_overlap,
        "chunk_count": int(row.chunk_count or 0),
        "vector_chunk_count": int(row.vector_chunk_count or 0),
        "attempt_count": int(row.attempt_count or 0),
        "last_error": safe_last_error,
        "last_error_code": error_code,
        "last_error_fingerprint": error_fingerprint,
        "last_indexed_at": to_utc_iso(row.last_indexed_at) if row.last_indexed_at else None,
        "updated_at": to_utc_iso(updated_at) if updated_at else None,
    }


class RetrievalProjectionService:
    """Own every material index mutation behind one durable lifecycle boundary."""

    def __init__(self, db: AsyncSession, rag: RAGService | None = None) -> None:
        self.db = db
        self.rag = rag or get_rag_service()

    async def get_projection(self, user_id: int, material_id: int) -> RetrievalProjection | None:
        result = await self.db.execute(
            select(RetrievalProjection).where(
                RetrievalProjection.user_id == int(user_id),
                RetrievalProjection.source_type == SOURCE_TYPE,
                RetrievalProjection.source_id == int(material_id),
                RetrievalProjection.backend == PROJECTION_BACKEND,
            )
        )
        return result.scalar_one_or_none()

    async def projection_map(self, user_id: int, material_ids: Sequence[int]) -> dict[int, dict[str, Any]]:
        ids = sorted({int(item) for item in material_ids})
        if not ids:
            return {}
        result = await self.db.execute(
            select(RetrievalProjection).where(
                RetrievalProjection.user_id == int(user_id),
                RetrievalProjection.source_type == SOURCE_TYPE,
                RetrievalProjection.source_id.in_(ids),
                RetrievalProjection.status != "deleted",
            )
        )
        return {
            int(row.source_id): serialize_projection(row) or {}
            for row in result.scalars().all()
        }

    async def project_ids(self, material_id: int, user_id: int) -> list[int]:
        result = await self.db.execute(
            select(ChatProjectMaterial.project_id)
            .join(ChatProject, ChatProject.id == ChatProjectMaterial.project_id)
            .where(
                ChatProject.user_id == int(user_id),
                ChatProjectMaterial.material_id == int(material_id),
            )
        )
        return sorted({int(row[0]) for row in result.all()})

    async def _replace_chunks(
        self,
        projection: RetrievalProjection,
        chunks: Sequence[str],
    ) -> None:
        await self.db.execute(
            delete(RetrievalProjectionChunk).where(
                RetrievalProjectionChunk.projection_id == int(projection.id)
            )
        )
        for index, text in enumerate(chunks):
            self.db.add(
                RetrievalProjectionChunk(
                    projection_id=int(projection.id),
                    user_id=int(projection.user_id),
                    source_type=SOURCE_TYPE,
                    source_id=int(projection.source_id),
                    source_version=int(projection.source_version),
                    chunk_index=index,
                    chunk_hash=_sha256(text),
                    text=text,
                )
            )

    async def _ensure_projection(
        self,
        user_id: int,
        material_id: int,
        *,
        operation: str,
    ) -> RetrievalProjection:
        values = {
            "user_id": int(user_id),
            "source_type": SOURCE_TYPE,
            "source_id": int(material_id),
            "backend": PROJECTION_BACKEND,
            "status": "pending",
            "last_operation": operation,
            "source_version": 1,
            "attempt_count": 0,
            "chunk_count": 0,
            "vector_chunk_count": 0,
        }
        dialect_name = self.db.bind.dialect.name if self.db.bind is not None else ""
        if dialect_name == "postgresql":
            statement = (
                postgresql_insert(RetrievalProjection)
                .values(**values)
                .on_conflict_do_nothing(
                    constraint="uq_retrieval_projection_source_backend"
                )
            )
            await self.db.execute(statement)
        elif dialect_name == "sqlite":
            statement = (
                sqlite_insert(RetrievalProjection)
                .values(**values)
                .on_conflict_do_nothing(
                    index_elements=["user_id", "source_type", "source_id", "backend"]
                )
            )
            await self.db.execute(statement)
        else:
            projection = await self.get_projection(user_id, material_id)
            if projection is None:
                projection = RetrievalProjection(**values)
                self.db.add(projection)
                await self.db.flush()
            return projection

        projection = await self.db.scalar(
            select(RetrievalProjection)
            .where(
                RetrievalProjection.user_id == int(user_id),
                RetrievalProjection.source_type == SOURCE_TYPE,
                RetrievalProjection.source_id == int(material_id),
                RetrievalProjection.backend == PROJECTION_BACKEND,
            )
            .execution_options(populate_existing=True)
        )
        if projection is None:
            raise RuntimeError("retrieval projection upsert did not produce a readable row")
        return projection

    async def ingest(
        self,
        material: Material,
        *,
        user_id: int,
        operation: str = "ingest",
        force: bool = False,
        project_ids: Sequence[int] | None = None,
        sync_vectors: bool = True,
    ) -> dict[str, Any]:
        """Serialize one user's vector mutations and reload canonical SQL state."""
        material_id = int(material.id)
        if int(material.user_id) != int(user_id):
            raise PermissionError("Cannot project a material owned by another user")
        async with serialized_retrieval_mutation(self.db, user_id=int(user_id)):
            canonical = await self.db.scalar(
                select(Material)
                .where(
                    Material.id == material_id,
                    Material.user_id == int(user_id),
                )
                .execution_options(populate_existing=True)
            )
            if canonical is None:
                projection = await self.get_projection(int(user_id), material_id)
                if projection is not None:
                    return serialize_projection(projection) or {}
                raise LookupError("资料不存在，无法建立检索投影。")
            return await self._ingest_locked(
                canonical,
                user_id=int(user_id),
                operation=operation,
                force=force,
                project_ids=project_ids,
                sync_vectors=sync_vectors,
            )

    async def _ingest_locked(
        self,
        material: Material,
        *,
        user_id: int,
        operation: str = "ingest",
        force: bool = False,
        project_ids: Sequence[int] | None = None,
        sync_vectors: bool = True,
    ) -> dict[str, Any]:
        """Persist a sparse manifest first; vectors may safely degrade or retry."""
        material_id = int(material.id)
        if int(material.user_id) != int(user_id):
            raise PermissionError("Cannot project a material owned by another user")

        normalized_project_ids = (
            sorted({int(value) for value in project_ids})
            if project_ids is not None
            else await self.project_ids(material_id, int(user_id))
        )
        content = str(material.content or "")
        content_hash = str(material.content_hash or _sha256(content))
        source_signature = _sha256(
            json.dumps(
                {
                    "title": str(material.title or ""),
                    "content_hash": content_hash,
                    "file_type": str(material.file_type or ""),
                    "project_ids": normalized_project_ids,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        config = retrieval_configuration(self.rag)
        projection = await self._ensure_projection(int(user_id), material_id, operation=operation)
        unchanged = (
            projection.source_signature == source_signature
            and projection.configuration_fingerprint == config["fingerprint"]
        )
        if unchanged and projection.status == "ready" and not force:
            return serialize_projection(projection) or {}

        if projection.source_signature and projection.source_signature != source_signature:
            projection.source_version = int(projection.source_version or 1) + 1
        projection.status = "indexing"
        projection.last_operation = operation
        projection.source_signature = source_signature
        projection.content_hash = content_hash
        projection.configuration_fingerprint = str(config["fingerprint"])
        projection.embedding_model = str(config["embedding_model"])
        projection.chunk_size = int(config["chunk_size"])
        projection.chunk_overlap = int(config["chunk_overlap"])
        projection.attempt_count = int(projection.attempt_count or 0) + 1
        projection.last_error = None
        projection.deleted_at = None
        projection.vector_chunk_count = 0

        chunks = _chunk_material_text(content) if content.strip() else []
        await self._replace_chunks(projection, chunks)
        projection.chunk_count = len(chunks)
        await self.db.commit()

        if not chunks:
            projection.status = "failed"
            projection.last_error = "资料没有可索引的文本内容。"
            await self.db.commit()
            return serialize_projection(projection) or {}

        if not settings.RAG_ENABLED or not sync_vectors:
            projection.status = "degraded"
            projection.last_error = (
                "本次资料未启用向量同步；SQL 关键词检索仍然可用。"
                if not sync_vectors
                else "向量检索未启用；SQL 关键词检索仍然可用。"
            )
            await self.db.commit()
            return serialize_projection(projection) or {}

        try:
            await self.rag.initialize()
            status = await self.rag.get_status(int(user_id))
            if not status.get("embedding_enabled"):
                projection.status = "degraded"
                projection.last_error = "未配置 embedding；SQL 关键词检索仍然可用。"
                await self.db.commit()
                return serialize_projection(projection) or {}

            count = await self.rag.index_material(
                material_id=material_id,
                title=str(material.title or ""),
                content=content,
                file_type=material.file_type,
                project_ids=normalized_project_ids,
                user_id=int(user_id),
            )
            if int(count or 0) <= 0:
                current_status = await self.rag.get_status(int(user_id))
                raise RuntimeError(
                    str(current_status.get("last_error") or "向量索引未生成任何片段。")
                )
        except Exception as exc:
            cleanup_error = ""
            try:
                await self.rag.remove_material(material_id, user_id=int(user_id))
            except Exception as cleanup_exc:
                cleanup_error = f"；残留清理失败：{safe_exception_summary(cleanup_exc)}"
            projection.status = "failed"
            projection.last_error = _safe_error(f"{safe_exception_summary(exc)}{cleanup_error}")
            projection.vector_chunk_count = 0
            logger.warning(
                "retrieval projection failed user_id=%s material_id=%s operation=%s: %s",
                user_id,
                material_id,
                operation,
                projection.last_error,
            )
            await self.db.commit()
            return serialize_projection(projection) or {}

        projection.status = "ready"
        projection.indexed_version = int(projection.source_version)
        projection.vector_chunk_count = int(count)
        projection.last_error = None
        projection.last_indexed_at = _utcnow()
        await self.db.commit()
        return serialize_projection(projection) or {}

    async def refresh(self, material: Material, *, user_id: int) -> dict[str, Any]:
        return await self.ingest(material, user_id=user_id, operation="refresh")

    async def prepare_forget(self, user_id: int, material_id: int) -> RetrievalProjection:
        """Mark a tombstone inside the same transaction as canonical deletion."""
        projection = await self._ensure_projection(user_id, material_id, operation="forget")
        projection.status = "deleting"
        projection.last_operation = "forget"
        projection.last_error = None
        await self._replace_chunks(projection, [])
        projection.chunk_count = 0
        await self.db.flush()
        return projection

    async def forget(self, user_id: int, material_id: int) -> dict[str, Any]:
        async with serialized_retrieval_mutation(self.db, user_id=int(user_id)):
            return await self._forget_locked(int(user_id), int(material_id))

    async def _forget_locked(self, user_id: int, material_id: int) -> dict[str, Any]:
        projection = await self.get_projection(user_id, material_id)
        if projection is None:
            projection = await self.prepare_forget(user_id, material_id)
            await self.db.commit()
        if projection.status == "deleted":
            return serialize_projection(projection) or {}

        projection.status = "deleting"
        projection.last_operation = "forget"
        projection.attempt_count = int(projection.attempt_count or 0) + 1
        await self.db.commit()

        try:
            await self.rag.initialize()
            await self.rag.remove_material(int(material_id), user_id=int(user_id))
        except Exception as exc:
            projection.status = "failed"
            projection.last_error = _safe_error(f"删除向量投影失败：{safe_exception_summary(exc)}")
            await self.db.commit()
            return serialize_projection(projection) or {}

        await self._replace_chunks(projection, [])
        projection.status = "deleted"
        projection.chunk_count = 0
        projection.vector_chunk_count = 0
        projection.last_error = None
        projection.deleted_at = _utcnow()
        await self.db.commit()
        return serialize_projection(projection) or {}

    async def retry(self, user_id: int, material_id: int) -> dict[str, Any]:
        projection = await self.get_projection(user_id, material_id)
        if projection is not None and projection.last_operation == "forget":
            return await self.forget(user_id, material_id)
        material = await self.db.scalar(
            select(Material).where(Material.id == int(material_id), Material.user_id == int(user_id))
        )
        if material is None:
            raise LookupError("资料不存在，无法重试索引。")
        return await self.ingest(material, user_id=user_id, operation="retry", force=True)

    async def rebuild_user(
        self,
        user_id: int,
        *,
        material_ids: Sequence[int] | None = None,
    ) -> dict[str, Any]:
        async with serialized_retrieval_mutation(self.db, user_id=int(user_id)):
            return await self._rebuild_user_locked(
                int(user_id),
                material_ids=material_ids,
            )

    async def _rebuild_user_locked(
        self,
        user_id: int,
        *,
        material_ids: Sequence[int] | None = None,
    ) -> dict[str, Any]:
        ids = sorted({int(item) for item in material_ids or []})
        if material_ids is not None and not ids:
            return {
                "ok": True,
                "materials_total": 0,
                "materials_indexed": 0,
                "failed": 0,
                "degraded": 0,
                "total_chunks": 0,
                "failures": [],
                "message": "没有需要重建的资料。",
            }

        query = select(Material).where(Material.user_id == int(user_id))
        if material_ids is not None:
            query = query.where(Material.id.in_(ids))
        result = await self.db.execute(query.order_by(Material.id))
        materials = list(result.scalars().all())

        if material_ids is None:
            try:
                await self.rag.initialize()
                await asyncio.to_thread(
                    self.rag._collection.delete,
                    where={"user_id": str(user_id)},
                )
            except Exception as exc:
                logger.warning(
                    "user-scoped vector pre-clean failed user_id=%s: %s",
                    user_id,
                    safe_exception_summary(exc),
                )

        indexed = 0
        degraded = 0
        total_chunks = 0
        failures: list[dict[str, Any]] = []
        for material in materials:
            projection = await self._ingest_locked(
                material,
                user_id=int(user_id),
                operation="rebuild",
                force=True,
            )
            if projection["status"] == "ready":
                indexed += 1
                total_chunks += int(projection["vector_chunk_count"])
            elif projection["status"] == "degraded":
                degraded += 1
            else:
                failures.append(
                    {
                        "material_id": int(material.id),
                        "title": str(material.title or ""),
                        "error": projection.get("last_error"),
                    }
                )

        return {
            "ok": not failures and not degraded,
            "materials_total": len(materials),
            "materials_indexed": indexed,
            "failed": len(failures),
            "degraded": degraded,
            "total_chunks": total_chunks,
            "failures": failures,
            "message": (
                f"已重建 {indexed}/{len(materials)} 份资料，共 {total_chunks} 个向量片段"
                if not failures and not degraded
                else f"重建完成：{indexed} 份成功，{degraded} 份关键词降级，{len(failures)} 份失败"
            ),
        }

    async def forget_user(self, user_id: int) -> dict[str, Any]:
        """Physically purge only one user's vector and SQL retrieval projections."""
        async with serialized_retrieval_mutation(self.db, user_id=int(user_id)):
            return await self._forget_user_locked(int(user_id))

    async def _forget_user_locked(self, user_id: int) -> dict[str, Any]:
        await self.rag.initialize()
        await asyncio.to_thread(self.rag._collection.delete, where={"user_id": str(user_id)})
        result = await self.db.execute(
            select(RetrievalProjection).where(RetrievalProjection.user_id == int(user_id))
        )
        projections = list(result.scalars().all())
        for projection in projections:
            await self._replace_chunks(projection, [])
            projection.status = "deleted"
            projection.last_operation = "forget"
            projection.chunk_count = 0
            projection.vector_chunk_count = 0
            projection.last_error = None
            projection.deleted_at = _utcnow()
        await self.db.commit()
        return {"ok": True, "user_id": int(user_id), "projections_deleted": len(projections)}

    async def mark_configuration_stale(
        self,
        *,
        user_id: Optional[int] = None,
        configuration_lock_held: bool = False,
    ) -> int:
        """Flag incompatible manifests after global model/chunk settings change."""
        if not configuration_lock_held:
            async with serialized_retrieval_configuration_change(self.db):
                return await self.mark_configuration_stale(
                    user_id=user_id,
                    configuration_lock_held=True,
                )
        config = retrieval_configuration(self.rag)
        query = select(RetrievalProjection).where(
            RetrievalProjection.status.not_in(("deleted", "deleting"))
        )
        if user_id is not None:
            query = query.where(RetrievalProjection.user_id == int(user_id))
        result = await self.db.execute(query)
        changed = 0
        for projection in result.scalars().all():
            if projection.configuration_fingerprint == config["fingerprint"]:
                continue
            projection.status = "degraded"
            projection.vector_chunk_count = 0
            projection.last_error = "Embedding 模型或分块配置已变更，请重建资料索引。"
            changed += 1
        if changed:
            await self.db.commit()
        return changed

    async def status_summary(self, user_id: int) -> dict[str, Any]:
        result = await self.db.execute(
            select(RetrievalProjection).where(RetrievalProjection.user_id == int(user_id))
        )
        projections = list(result.scalars().all())
        counts = Counter(str(row.status) for row in projections)
        active = [row for row in projections if row.status != "deleted"]
        return {
            "total": len(active),
            "ready": counts.get("ready", 0),
            "pending": counts.get("pending", 0) + counts.get("indexing", 0),
            "degraded": counts.get("degraded", 0),
            "failed": counts.get("failed", 0),
            "deleting": counts.get("deleting", 0),
            "deleted": counts.get("deleted", 0),
            "sql_chunks": sum(int(row.chunk_count or 0) for row in active),
            "vector_chunks": sum(int(row.vector_chunk_count or 0) for row in active),
        }
