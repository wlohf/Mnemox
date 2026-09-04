"""RAG 知识库诊断路由。"""

import os

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Optional, List

from app.config import settings
from app.ai.rag_service import create_embedding_model, get_rag_service, load_rag_settings, save_rag_settings
from app.utils.outbound_url import validate_ai_provider_url
from app.database import get_db
from app.models.material import Material
from app.models.chat import ChatProjectMaterial, ChatProject
from app.auth import get_current_user
from app.models.user import User
from app.services.retrieval_projection_service import (
    RetrievalProjectionService,
    serialized_retrieval_configuration_change,
)
from app.services.knowledge_projection_service import (
    invalidate_knowledge_embedding_configuration,
)
from app.utils.ai_errors import format_ai_provider_error
from app.utils.error_safety import redact_sensitive_text


router = APIRouter()


def _mask_key(key: str) -> str:
    """将 API key 脱敏显示"""
    if not key:
        return ""
    if len(key) <= 8:
        return "****"
    return key[:3] + "****" + key[-4:]


def _require_rag_settings_manager(current_user: User) -> None:
    """Keep process-wide embedding settings out of ordinary user control."""
    is_public = settings.ENVIRONMENT.lower() in {"prod", "production"} or bool(os.environ.get("DB_PASSWORD"))
    if not is_public:
        return
    allowed = {
        item.strip().casefold()
        for item in settings.RAG_SETTINGS_ADMIN_USERNAMES.split(",")
        if item.strip()
    }
    if current_user.username.casefold() not in allowed:
        raise HTTPException(status_code=403, detail="仅部署管理员可以修改全局 RAG 配置")


def _coerce_rag_number(value, fallback, cast_type):
    if value is None:
        return fallback
    try:
        return cast_type(value)
    except (TypeError, ValueError):
        return fallback


def _validate_rag_runtime_settings(config: dict) -> dict:
    chunk_size = _coerce_rag_number(config.get("chunk_size"), settings.RAG_CHUNK_SIZE, int)
    chunk_overlap = _coerce_rag_number(config.get("chunk_overlap"), settings.RAG_CHUNK_OVERLAP, int)
    top_k = _coerce_rag_number(config.get("top_k"), settings.RAG_TOP_K, int)
    similarity_threshold = _coerce_rag_number(
        config.get("similarity_threshold"),
        settings.RAG_SIMILARITY_THRESHOLD,
        float,
    )

    if chunk_size < 64 or chunk_size > 4096:
        raise HTTPException(status_code=400, detail="Chunk Size 必须在 64 到 4096 之间")
    if chunk_overlap < 0 or chunk_overlap >= chunk_size:
        raise HTTPException(status_code=400, detail="Chunk Overlap 必须大于等于 0 且小于 Chunk Size")
    if top_k < 1 or top_k > 50:
        raise HTTPException(status_code=400, detail="Top K 必须在 1 到 50 之间")
    if similarity_threshold < 0 or similarity_threshold > 1:
        raise HTTPException(status_code=400, detail="Similarity Threshold 必须在 0 到 1 之间")

    config["chunk_size"] = chunk_size
    config["chunk_overlap"] = chunk_overlap
    config["top_k"] = top_k
    config["similarity_threshold"] = similarity_threshold
    return config


# ------------------------------------------------------------------
# RAG Embedding 设置
# ------------------------------------------------------------------

class RagSettingsUpdate(BaseModel):
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    model: Optional[str] = None
    chunk_size: Optional[int] = None
    chunk_overlap: Optional[int] = None
    top_k: Optional[int] = None
    similarity_threshold: Optional[float] = None


@router.get("/settings")
async def get_rag_settings_endpoint(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取当前 RAG embedding 配置（api_key 脱敏）。"""
    file_cfg = load_rag_settings()
    api_key = file_cfg.get("api_key") or settings.OPENAI_API_KEY
    base_url = file_cfg.get("base_url") or settings.OPENAI_BASE_URL
    model = file_cfg.get("model") or settings.RAG_EMBEDDING_MODEL

    rag = get_rag_service()
    status = await rag.get_status(int(current_user.id))

    return {
        "api_key_masked": _mask_key(api_key),
        "base_url": base_url,
        "model": model,
        "initialized": status["initialized"],
        "total_chunks": status.get("total_chunks", 0),
        "chunk_size": status.get("chunk_size", settings.RAG_CHUNK_SIZE),
        "chunk_overlap": status.get("chunk_overlap", settings.RAG_CHUNK_OVERLAP),
        "top_k": status.get("top_k", settings.RAG_TOP_K),
        "similarity_threshold": status.get("similarity_threshold", settings.RAG_SIMILARITY_THRESHOLD),
        "embedding_enabled": status.get("embedding_enabled", False),
        "last_error": status.get("last_error", ""),
        "last_error_code": status.get("last_error_code"),
        "last_error_fingerprint": status.get("last_error_fingerprint"),
        "last_retrieval_status": status.get("last_retrieval_status", {}),
        "fallback_active": status.get("fallback_active", False),
        "projection_summary": await RetrievalProjectionService(db, rag=rag).status_summary(
            int(current_user.id)
        ),
    }


@router.put("/settings")
async def update_rag_settings(
    body: RagSettingsUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """更新 RAG embedding 配置并热重载服务。"""
    _require_rag_settings_manager(current_user)
    current = load_rag_settings()

    if body.api_key is not None and body.api_key != "":
        current["api_key"] = body.api_key
    if body.base_url is not None:
        current["base_url"] = body.base_url
    if body.model is not None:
        current["model"] = body.model
    if body.chunk_size is not None:
        current["chunk_size"] = body.chunk_size
    if body.chunk_overlap is not None:
        current["chunk_overlap"] = body.chunk_overlap
    if body.top_k is not None:
        current["top_k"] = body.top_k
    if body.similarity_threshold is not None:
        current["similarity_threshold"] = body.similarity_threshold

    current = _validate_rag_runtime_settings(current)

    # 热重载 RAG 服务
    api_key = current.get("api_key") or settings.OPENAI_API_KEY
    base_url = current.get("base_url") or settings.OPENAI_BASE_URL
    if api_key:
        try:
            base_url = await validate_ai_provider_url(base_url)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=redact_sensitive_text(exc)) from exc
        current["base_url"] = base_url
    model = current.get("model") or settings.RAG_EMBEDDING_MODEL
    rag = get_rag_service()
    async with serialized_retrieval_configuration_change(db):
        save_rag_settings(current)
        await rag.reinitialize(
            api_key=api_key,
            base_url=base_url,
            model=model,
            chunk_size=current.get("chunk_size"),
            chunk_overlap=current.get("chunk_overlap"),
            top_k=current.get("top_k"),
            similarity_threshold=current.get("similarity_threshold"),
        )
        status = await rag.get_status(int(current_user.id))
        status_message = (status.get("last_retrieval_status") or {}).get("message", "")
        stale_count = await RetrievalProjectionService(db, rag=rag).mark_configuration_stale(
            configuration_lock_held=True
        )
        knowledge_change = (
            await invalidate_knowledge_embedding_configuration(db)
            if settings.KNOWLEDGE_V2_ENABLED
            else {"users": 0, "stale_projections": 0, "rebuilds_enqueued": 0}
        )

    return {
        "ok": True,
        "api_key_masked": _mask_key(api_key),
        "base_url": base_url,
        "model": model,
        "requires_reindex": "重新索引" in status_message or stale_count > 0,
        "stale_projections": stale_count,
        "stale_knowledge_projections": knowledge_change["stale_projections"],
        "knowledge_rebuilds_enqueued": knowledge_change["rebuilds_enqueued"],
        "message": status_message,
        "total_chunks": status.get("total_chunks", 0),
    }


@router.post("/test-embedding")
async def test_rag_embedding(
    current_user: User = Depends(get_current_user),
):
    """使用当前配置测试 embedding 连接。"""
    _require_rag_settings_manager(current_user)
    file_cfg = load_rag_settings()
    api_key = file_cfg.get("api_key") or settings.OPENAI_API_KEY
    base_url = file_cfg.get("base_url") or settings.OPENAI_BASE_URL
    model = file_cfg.get("model") or settings.RAG_EMBEDDING_MODEL

    if not api_key:
        return {"success": False, "message": "未配置 API Key", "capability": "embedding", "model": model}

    try:
        base_url = await validate_ai_provider_url(base_url)
    except ValueError as exc:
        return {
            "success": False,
            "message": redact_sensitive_text(exc),
            "capability": "embedding",
            "model": model,
        }

    import asyncio

    def _test():
        embed = create_embedding_model(
            model=model,
            api_key=api_key,
            base_url=base_url,
        )
        result = embed.get_text_embedding("Hello, this is a test.")
        return len(result)

    try:
        dim = await asyncio.to_thread(_test)
        return {"success": True, "message": f"Embedding 连接成功！维度: {dim}", "capability": "embedding", "model": model}
    except Exception as e:
        return {
            "success": False,
            "message": f"Embedding 连接失败: {format_ai_provider_error(e)}",
            "capability": "embedding",
            "model": model,
        }


@router.get("/health")
async def rag_health(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    检查 RAG 知识库服务状态。

    返回的数据用于前端展示连接状态。
    """
    rag = get_rag_service()
    status = await rag.get_status(int(current_user.id))

    return {
        "enabled": status["enabled"],
        "initialized": status["initialized"],
        "total_chunks": status.get("total_chunks", 0),
        "embedding_model": status.get("embedding_model", ""),
        "chunk_size": status.get("chunk_size", 0),
        "rag_online": status["initialized"] and status.get("embedding_enabled", False),
        "embedding_enabled": status.get("embedding_enabled", False),
        "fallback_active": status.get("fallback_active", False),
        "last_error": status.get("last_error", ""),
        "last_error_code": status.get("last_error_code"),
        "last_error_fingerprint": status.get("last_error_fingerprint"),
        "last_retrieval_status": status.get("last_retrieval_status", {}),
        "message": status.get("message", ""),
        "projection_summary": await RetrievalProjectionService(db, rag=rag).status_summary(
            int(current_user.id)
        ),
    }


@router.get("/projections")
async def list_retrieval_projections(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Expose only the authenticated user's durable retrieval lifecycle state."""
    from app.models.retrieval import RetrievalProjection
    from app.services.retrieval_projection_service import serialize_projection

    result = await db.execute(
        select(RetrievalProjection)
        .where(RetrievalProjection.user_id == int(current_user.id))
        .order_by(RetrievalProjection.updated_at.desc(), RetrievalProjection.id.desc())
    )
    return {
        "items": [serialize_projection(row) for row in result.scalars().all()],
        "summary": await RetrievalProjectionService(db).status_summary(int(current_user.id)),
    }


@router.post("/projections/{material_id}/retry")
async def retry_retrieval_projection(
    material_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = RetrievalProjectionService(db)
    projection = await service.get_projection(int(current_user.id), material_id)
    if projection is None:
        raise HTTPException(status_code=404, detail="检索投影不存在")
    try:
        return await service.retry(int(current_user.id), material_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=redact_sensitive_text(exc)) from exc


@router.post("/reindex/{material_id}")
async def reindex_material(
    material_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """重新索引指定资料。"""
    if not settings.RAG_ENABLED:
        return {"ok": False, "message": "RAG 未启用"}

    # Verify material belongs to user
    result = await db.execute(
        select(Material).where(Material.id == material_id, Material.user_id == current_user.id)
    )
    material = result.scalar_one_or_none()
    if not material:
        return {"ok": False, "message": "资料不存在"}
    if not material.content:
        return {"ok": False, "message": "资料无文本内容"}

    projection = await RetrievalProjectionService(db).ingest(
        material,
        user_id=int(current_user.id),
        operation="rebuild",
        force=True,
    )
    return {
        "ok": projection.get("status") == "ready",
        "chunk_count": int(projection.get("vector_chunk_count") or 0),
        "message": projection.get("last_error") or "资料索引已重建。",
        "projection": projection,
    }


@router.post("/reindex-all")
async def reindex_all(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """重新索引当前用户的所有资料，不清空其他用户的 Chroma chunk。"""
    if not settings.RAG_ENABLED:
        return {"ok": False, "message": "RAG 未启用"}

    return await RetrievalProjectionService(db, rag=get_rag_service()).rebuild_user(
        int(current_user.id)
    )


async def _get_material_project_ids(db: AsyncSession, material_id: int, user_id: int) -> List[int]:
    result = await db.execute(
        select(ChatProjectMaterial.project_id)
        .join(ChatProject, ChatProjectMaterial.project_id == ChatProject.id)
        .where(ChatProject.user_id == user_id)
        .where(ChatProjectMaterial.material_id == material_id)
    )
    return [row[0] for row in result.all()]
