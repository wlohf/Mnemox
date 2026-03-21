"""RAG 知识库诊断路由。"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Optional, List

from app.config import settings
from app.ai.rag_service import get_rag_service, load_rag_settings, save_rag_settings
from app.database import get_db
from app.models.material import Material
from app.models.chat import ChatProjectMaterial, ChatProject
from app.auth import get_current_user
from app.models.user import User


router = APIRouter()


def _mask_key(key: str) -> str:
    """将 API key 脱敏显示"""
    if not key:
        return ""
    if len(key) <= 8:
        return "****"
    return key[:3] + "****" + key[-4:]


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
    current_user: User = Depends(get_current_user),
):
    """获取当前 RAG embedding 配置（api_key 脱敏）。"""
    file_cfg = load_rag_settings()
    api_key = file_cfg.get("api_key") or settings.OPENAI_API_KEY
    base_url = file_cfg.get("base_url") or settings.OPENAI_BASE_URL
    model = file_cfg.get("model") or settings.RAG_EMBEDDING_MODEL

    rag = get_rag_service()
    status = await rag.get_status()

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
    }


@router.put("/settings")
async def update_rag_settings(
    body: RagSettingsUpdate,
    current_user: User = Depends(get_current_user),
):
    """更新 RAG embedding 配置并热重载服务。"""
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

    save_rag_settings(current)

    # 热重载 RAG 服务
    api_key = current.get("api_key") or settings.OPENAI_API_KEY
    base_url = current.get("base_url") or settings.OPENAI_BASE_URL
    model = current.get("model") or settings.RAG_EMBEDDING_MODEL

    rag = get_rag_service()
    await rag.reinitialize(
        api_key=api_key,
        base_url=base_url,
        model=model,
        chunk_size=current.get("chunk_size"),
        chunk_overlap=current.get("chunk_overlap"),
        top_k=current.get("top_k"),
        similarity_threshold=current.get("similarity_threshold"),
    )

    return {
        "ok": True,
        "api_key_masked": _mask_key(api_key),
        "base_url": base_url,
        "model": model,
    }


@router.post("/test-embedding")
async def test_rag_embedding(
    current_user: User = Depends(get_current_user),
):
    """使用当前配置测试 embedding 连接。"""
    file_cfg = load_rag_settings()
    api_key = file_cfg.get("api_key") or settings.OPENAI_API_KEY
    base_url = file_cfg.get("base_url") or settings.OPENAI_BASE_URL
    model = file_cfg.get("model") or settings.RAG_EMBEDDING_MODEL

    if not api_key:
        return {"success": False, "message": "未配置 API Key"}

    import asyncio

    def _test():
        from llama_index.embeddings.openai import OpenAIEmbedding

        api_base = base_url if base_url != "https://api.openai.com/v1" else None
        embed = OpenAIEmbedding(
            model_name=model,
            api_key=api_key,
            api_base=api_base,
        )
        result = embed.get_text_embedding("Hello, this is a test.")
        return len(result)

    try:
        dim = await asyncio.to_thread(_test)
        return {"success": True, "message": f"连接成功！Embedding 维度: {dim}"}
    except Exception as e:
        return {"success": False, "message": f"连接失败: {str(e)}"}


@router.get("/health")
async def rag_health(
    current_user: User = Depends(get_current_user),
):
    """
    检查 RAG 知识库服务状态。

    返回的数据用于前端展示连接状态。
    """
    rag = get_rag_service()
    status = await rag.get_status()

    return {
        "enabled": status["enabled"],
        "initialized": status["initialized"],
        "total_chunks": status.get("total_chunks", 0),
        "embedding_model": status.get("embedding_model", ""),
        "chunk_size": status.get("chunk_size", 0),
        "rag_online": status["initialized"],
        "message": status.get("message", ""),
    }


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

    rag = get_rag_service()
    project_ids = await _get_material_project_ids(db, material.id, current_user.id)
    count = await rag.index_material(
        material_id=material.id,
        title=material.title,
        content=material.content,
        file_type=material.file_type,
        project_ids=project_ids,
    )
    return {"ok": True, "chunk_count": count}


@router.post("/reindex-all")
async def reindex_all(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """重新索引当前用户的所有资料。"""
    if not settings.RAG_ENABLED:
        return {"ok": False, "message": "RAG 未启用"}

    result = await db.execute(
        select(Material).where(
            Material.content.is_not(None),
            Material.user_id == current_user.id,
        )
    )
    materials = result.scalars().all()

    rag = get_rag_service()
    total_chunks = 0
    for mat in materials:
        project_ids = await _get_material_project_ids(db, mat.id, current_user.id)
        count = await rag.index_material(
            material_id=mat.id,
            title=mat.title,
            content=mat.content,
            file_type=mat.file_type,
            project_ids=project_ids,
        )
        total_chunks += count

    return {
        "ok": True,
        "materials_indexed": len(materials),
        "total_chunks": total_chunks,
    }
async def _get_material_project_ids(db: AsyncSession, material_id: int, user_id: int) -> List[int]:
    result = await db.execute(
        select(ChatProjectMaterial.project_id)
        .join(ChatProject, ChatProjectMaterial.project_id == ChatProject.id)
        .where(ChatProject.user_id == user_id)
        .where(ChatProjectMaterial.material_id == material_id)
    )
    return [row[0] for row in result.all()]
