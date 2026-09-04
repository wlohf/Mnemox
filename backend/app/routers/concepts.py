"""概念图谱 API（决策 D2）。"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.factory import AIProviderFactory
from app.auth import get_current_user
from app.config import settings
from app.database import get_db
from app.models.material import Chapter, Material
from app.models.user import User
from app.services.association_coach_service import create_association_recall_nudge
from app.services.association_service import find_associations
from app.utils.ai_errors import format_ai_provider_error
from app.utils.error_safety import redact_sensitive_text, safe_exception_summary
from app.services.concept_service import (
    backfill_wrong_question_concepts,
    extract_chapter_concepts_llm,
    get_concept_neighborhood,
    list_concepts,
    upsert_concept,
)
from app.services.concept_graph_service import (
    add_concept_alias,
    create_concept_relation,
    delete_concept,
    get_concept_detail,
    get_prerequisite_gaps,
    list_concept_audit,
    merge_concepts,
    rename_concept,
    review_concept,
    review_concept_relation,
    split_concept,
    sync_material_concepts,
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

    if settings.KNOWLEDGE_V2_ENABLED:
        from app.services.knowledge_extraction_service import (
            create_extraction_run,
            serialize_extraction_run,
        )
        from app.services.knowledge_source_service import register_material_source

        revision = await register_material_source(
            db,
            user_id=user_id,
            material_id=int(material_id),
        )
        extractor_type = "llm" if settings.KNOWLEDGE_LLM_EXTRACTION_ENABLED else "deterministic"
        run = await create_extraction_run(
            db,
            user_id=user_id,
            source_revision_id=int(revision.id),
            extractor_type=extractor_type,
        )
        return {
            "material_id": int(material_id),
            "status": "queued" if run.status in {"queued", "failed"} else str(run.status),
            "extraction_run": serialize_extraction_run(run),
            "llm_enabled": bool(settings.KNOWLEDGE_LLM_EXTRACTION_ENABLED),
        }

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
        raise HTTPException(
            status_code=400,
            detail=f"AI Provider 不可用：{format_ai_provider_error(exc)}",
        ) from exc

    total = {"concepts": 0, "edges": 0}
    failed_chapters: list[str] = []
    for chapter in chapters:
        try:
            stats = await extract_chapter_concepts_llm(db, user_id, chapter, provider)
            total["concepts"] += stats["concepts"]
            total["edges"] += stats["edges"]
        except Exception as exc:
            logger.warning(
                "章节概念抽取失败 material_id=%s chapter_id=%s err=%s",
                material_id,
                chapter.id,
                safe_exception_summary(exc),
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


class AssociateRequest(BaseModel):
    text: str
    limit: int = 3


@router.post("/associate")
async def associate_text(
    body: AssociateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """联想引擎：对一段新内容返回与旧知识的关联（概念、证据、先修缺口）。"""
    if not (body.text or "").strip():
        raise HTTPException(status_code=400, detail="text 不能为空")
    associations = await find_associations(
        db, int(current_user.id), body.text, limit=body.limit
    )
    coach_result = None
    try:
        async with db.begin_nested():
            coach_result = await create_association_recall_nudge(
                db,
                int(current_user.id),
                query_text=body.text,
                associations=associations,
            )
    except Exception as exc:
        logger.warning(
            "联想结果已生成，但 Coach 归因写入失败 user_id=%s err=%s",
            current_user.id,
            safe_exception_summary(exc),
        )
    return {
        "associations": associations,
        "event": coach_result["event"] if coach_result else None,
        "nudge": coach_result["nudge"] if coach_result else None,
    }


class ConceptCreateRequest(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    description: str | None = Field(default=None, max_length=500)


class ConceptAliasRequest(BaseModel):
    alias: str = Field(min_length=2, max_length=120)


class ConceptMergeRequest(BaseModel):
    source_concept_id: int = Field(gt=0)


class ConceptSplitRequest(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    alias_ids: list[int] = Field(default_factory=list, max_length=100)
    source_evidence_ids: list[int] = Field(default_factory=list, max_length=100)
    link_ids: list[int] = Field(default_factory=list, max_length=100)


class ConceptReviewRequest(BaseModel):
    review_status: str = Field(pattern="^(confirmed|rejected)$")


class ConceptEdgeRequest(BaseModel):
    from_concept_id: int = Field(gt=0)
    to_concept_id: int = Field(gt=0)
    edge_type: str = Field(min_length=2, max_length=30)
    confidence: float = Field(default=1.0, ge=0, le=1)


def _graph_error(exc: Exception) -> HTTPException:
    return HTTPException(
        status_code=404 if isinstance(exc, LookupError) else 409,
        detail=redact_sensitive_text(exc),
    )


@router.post("")
async def create_concept(
    body: ConceptCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    concept = await upsert_concept(
        db, int(current_user.id), body.name, description=body.description, source="manual", review_status="confirmed",
    )
    if concept is None:
        raise HTTPException(status_code=422, detail="概念名称无效")
    return await get_concept_detail(db, int(current_user.id), int(concept.id))


@router.post("/edges")
async def create_edge(
    body: ConceptEdgeRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        return await create_concept_relation(
            db, int(current_user.id), body.from_concept_id, body.to_concept_id, body.edge_type,
            confidence=body.confidence,
        )
    except (LookupError, ValueError) as exc:
        raise _graph_error(exc) from exc


@router.post("/edges/{edge_id}/review")
async def review_edge(
    edge_id: int,
    body: ConceptReviewRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        return await review_concept_relation(db, int(current_user.id), edge_id, body.review_status)
    except (LookupError, ValueError) as exc:
        raise _graph_error(exc) from exc


@router.post("/materials/{material_id}/sync")
async def sync_material_graph(
    material_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    material = await get_owned_row(db, Material, material_id, int(current_user.id), not_found_detail="资料不存在")
    return await sync_material_concepts(db, int(current_user.id), material)


@router.get("/{concept_id}")
async def concept_detail(
    concept_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        return await get_concept_detail(db, int(current_user.id), concept_id)
    except LookupError as exc:
        raise _graph_error(exc) from exc


@router.get("/{concept_id}/prerequisite-gaps")
async def prerequisite_gaps(
    concept_id: int,
    depth: int = Query(3, ge=1, le=5),
    mastery_threshold: float = Query(70.0, ge=0, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        return {
            "concept_id": concept_id,
            "gaps": await get_prerequisite_gaps(
                db, int(current_user.id), concept_id, max_depth=depth, mastery_threshold=mastery_threshold,
            ),
        }
    except LookupError as exc:
        raise _graph_error(exc) from exc


@router.get("/{concept_id}/audit")
async def concept_audit(
    concept_id: int,
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        return {"items": await list_concept_audit(db, int(current_user.id), concept_id, limit=limit)}
    except LookupError as exc:
        raise _graph_error(exc) from exc


@router.patch("/{concept_id}")
async def update_concept(
    concept_id: int,
    body: ConceptCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        return await rename_concept(
            db, int(current_user.id), concept_id, name=body.name, description=body.description,
        )
    except (LookupError, ValueError) as exc:
        raise _graph_error(exc) from exc


@router.post("/{concept_id}/aliases")
async def create_alias(
    concept_id: int,
    body: ConceptAliasRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        return await add_concept_alias(db, int(current_user.id), concept_id, body.alias)
    except (LookupError, ValueError) as exc:
        raise _graph_error(exc) from exc


@router.post("/{concept_id}/review")
async def review_concept_candidate(
    concept_id: int,
    body: ConceptReviewRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        return await review_concept(db, int(current_user.id), concept_id, body.review_status)
    except (LookupError, ValueError) as exc:
        raise _graph_error(exc) from exc


@router.post("/{concept_id}/merge")
async def merge_concept(
    concept_id: int,
    body: ConceptMergeRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        return await merge_concepts(db, int(current_user.id), concept_id, body.source_concept_id)
    except (LookupError, ValueError) as exc:
        raise _graph_error(exc) from exc


@router.post("/{concept_id}/split")
async def split_concept_identity(
    concept_id: int,
    body: ConceptSplitRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        return await split_concept(
            db, int(current_user.id), concept_id, name=body.name, alias_ids=body.alias_ids,
            source_evidence_ids=body.source_evidence_ids, link_ids=body.link_ids,
        )
    except (LookupError, ValueError) as exc:
        raise _graph_error(exc) from exc


@router.delete("/{concept_id}")
async def remove_concept(
    concept_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        return await delete_concept(db, int(current_user.id), concept_id)
    except LookupError as exc:
        raise _graph_error(exc) from exc
