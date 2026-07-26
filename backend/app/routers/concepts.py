"""概念图谱 API（决策 D2）。"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.factory import AIProviderFactory
from app.auth import get_current_user
from app.database import get_db
from app.models.material import Chapter, Material
from app.models.user import User
from app.services.concept_service import (
    backfill_wrong_question_concepts,
    extract_chapter_concepts_llm,
    get_concept_neighborhood,
    list_concepts,
)
from app.utils.ownership import get_owned_row

router = APIRouter()
logger = logging.getLogger(__name__)

MAX_EXTRACT_CHAPTERS = 20


@router.get("")
async def get_concepts(
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """概念总览（按挂接数量排序）。"""
    return {"concepts": await list_concepts(db, int(current_user.id), limit=limit)}


@router.get("/{concept_id}/neighborhood")
async def get_neighborhood(
    concept_id: int,
    depth: int = Query(1, ge=1, le=2),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """概念邻域：关联概念、关系边与挂接的章节/笔记/错题/卡片。"""
    neighborhood = await get_concept_neighborhood(
        db, int(current_user.id), concept_id, depth=depth
    )
    if neighborhood is None:
        raise HTTPException(status_code=404, detail="概念不存在")
    return neighborhood


@router.post("/materials/{material_id}/extract")
async def extract_material_concepts(
    material_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """对资料的各章节做概念+关系抽取（每章一次 LLM 调用）。

    单章失败跳过不中断；全部失败时返回 partial 状态而非 5xx（降级纪律）。
    """
    user_id = int(current_user.id)
    await get_owned_row(db, Material, material_id, user_id, not_found_detail="资料不存在")

    chapter_result = await db.execute(
        select(Chapter)
        .where(Chapter.material_id == material_id)
        .order_by(Chapter.order_index.asc(), Chapter.id.asc())
        .limit(MAX_EXTRACT_CHAPTERS)
    )
    chapters = list(chapter_result.scalars().all())
    if not chapters:
        raise HTTPException(status_code=400, detail="该资料还没有章节，请先执行资料分析")

    try:
        provider = await AIProviderFactory.create_provider(
            db=db, scenario="material_analyze", user_id=user_id
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"AI Provider 不可用：{exc}") from exc

    total = {"concepts": 0, "edges": 0}
    failed_chapters: list[str] = []
    for chapter in chapters:
        try:
            stats = await extract_chapter_concepts_llm(db, user_id, chapter, provider)
            total["concepts"] += stats["concepts"]
            total["edges"] += stats["edges"]
        except Exception as exc:
            logger.warning(
                "章节概念抽取失败 material_id=%s chapter_id=%s err=%s", material_id, chapter.id, exc
            )
            failed_chapters.append(str(chapter.title or chapter.id))

    return {
        "material_id": material_id,
        "chapter_count": len(chapters),
        "created_concepts": total["concepts"],
        "created_edges": total["edges"],
        "failed_chapters": failed_chapters,
        "status": "ok" if not failed_chapters else ("partial" if total["concepts"] else "failed"),
    }


@router.post("/backfill/wrong-questions")
async def backfill_wrong_questions(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """把存量错题的知识点字符串回填为概念实体（决策 D1 数据迁移）。"""
    return await backfill_wrong_question_concepts(db, int(current_user.id))
