"""Grounded extraction, entity-resolution review, and projection lifecycle API."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.config import settings
from app.database import get_db
from app.models.knowledge import (
    Claim,
    ClaimConceptLink,
    EntityResolutionCandidate,
    KnowledgeExtractionRun,
    KnowledgeSource,
)
from app.models.material import Material
from app.models.user import User
from app.services.knowledge_extraction_service import (
    cancel_extraction_run,
    create_extraction_run,
    get_material_extraction_summary,
    retry_extraction_run,
    serialize_extraction_run,
)
from app.services.knowledge_lab_service import material_claim_snapshot
from app.services.knowledge_source_service import register_material_source, review_claim
from app.services.entity_resolution_service import (
    list_resolution_candidates,
    pending_resolution_count,
    resolve_candidate,
)
from app.services.knowledge_projection_service import (
    enqueue_user_knowledge_rebuild,
    knowledge_status_summary,
)
from app.services.graph_runtime_status_service import graph_runtime_status
from app.services.knowledge_path_service import (
    KnowledgePathUnavailable,
    build_learning_paths,
)
from app.utils.error_safety import redact_sensitive_text
from app.services.association_reranker_service import create_association_reranker
from app.services.association_v2_service import associate


router = APIRouter()


class ResolutionDecisionRequest(BaseModel):
    action: str = Field(pattern="^(link|link_add_alias|create_new|reject)$")
    concept_id: int | None = Field(default=None, gt=0)
    concept_name: str | None = Field(default=None, min_length=2, max_length=120)


class AssociationV2Request(BaseModel):
    text: str = Field(min_length=1, max_length=8_000)
    source_type: str | None = Field(default=None, pattern="^(material|note)$")
    source_id: int | None = Field(default=None, gt=0)
    limit: int = Field(default=5, ge=1, le=10)


class ClaimReviewRequest(BaseModel):
    review_status: Literal["confirmed", "rejected"]


class KnowledgePathRequest(BaseModel):
    start_concept_ids: list[int] = Field(min_length=1, max_length=10)
    target_concept_id: int = Field(gt=0)
    max_depth: int = Field(default=6, ge=1, le=8)
    relation_types: list[Literal["prerequisite_of", "related_to"]] = Field(
        default_factory=lambda: ["prerequisite_of"],
        min_length=1,
        max_length=2,
    )
    limit: int = Field(default=3, ge=1, le=5)


def _require_knowledge_v2() -> None:
    if not settings.KNOWLEDGE_V2_ENABLED:
        raise HTTPException(status_code=409, detail="Knowledge V2 尚未启用")


def _require_association_v2() -> None:
    _require_knowledge_v2()
    if not settings.ASSOCIATION_V2_ENABLED:
        raise HTTPException(status_code=409, detail="Association V2 尚未启用")


def _require_knowledge_path() -> None:
    _require_knowledge_v2()
    if not settings.KNOWLEDGE_PATH_ENABLED:
        raise HTTPException(status_code=409, detail="Knowledge Path 尚未启用")


@router.post("/learning-path")
async def knowledge_learning_path(
    body: KnowledgePathRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_knowledge_path()
    try:
        return await build_learning_paths(
            db,
            user_id=int(current_user.id),
            start_concept_ids=body.start_concept_ids,
            target_concept_id=body.target_concept_id,
            max_depth=body.max_depth,
            relation_types=body.relation_types,
            limit=body.limit,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="概念不存在或不可用") from exc
    except KnowledgePathUnavailable as exc:
        raise HTTPException(
            status_code=503,
            detail="Knowledge Path 需要已就绪的 Neo4j 图后端；当前高级路径能力不可用",
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=redact_sensitive_text(exc)) from exc


@router.post("/associate")
async def associate_knowledge(
    body: AssociationV2Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_association_v2()
    if (body.source_type is None) != (body.source_id is None):
        raise HTTPException(status_code=400, detail="source_type 与 source_id 必须同时提供")
    try:
        semantic_reranker = await create_association_reranker(
            db=db,
            user_id=int(current_user.id),
        )
        return await associate(
            db,
            user_id=int(current_user.id),
            text=body.text,
            source_type=body.source_type,
            source_id=body.source_id,
            limit=body.limit,
            semantic_reranker=semantic_reranker,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=redact_sensitive_text(exc)) from exc


@router.get("/materials/{material_id}/extraction")
async def material_extraction_status(
    material_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    owned = await db.scalar(
        select(Material.id).where(
            Material.id == int(material_id),
            Material.user_id == int(current_user.id),
        )
    )
    if owned is None:
        raise HTTPException(status_code=404, detail="资料不存在")
    return await get_material_extraction_summary(
        db,
        user_id=int(current_user.id),
        material_id=int(material_id),
    )


@router.get("/materials/{material_id}/claims")
async def material_claims_for_lab(
    material_id: int,
    review_status: str = Query(default="all", pattern="^(all|pending|confirmed|rejected)$"),
    limit: int = Query(default=200, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_knowledge_v2()
    try:
        return await material_claim_snapshot(
            db,
            user_id=int(current_user.id),
            material_id=int(material_id),
            review_status=review_status,
            limit=limit,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=404, detail="资料不存在") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=redact_sensitive_text(exc)) from exc


@router.post("/claims/{claim_id}/review")
async def review_knowledge_claim(
    claim_id: int,
    body: ClaimReviewRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_knowledge_v2()
    try:
        claim = await review_claim(
            db,
            user_id=int(current_user.id),
            claim_id=int(claim_id),
            review_status=body.review_status,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=404, detail="Claim 不存在") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=redact_sensitive_text(exc)) from exc
    return {
        "id": int(claim.id),
        "review_status": str(claim.review_status),
        "reviewed_at": claim.reviewed_at.isoformat() if claim.reviewed_at else None,
    }


@router.post("/materials/{material_id}/extract")
async def enqueue_material_extraction(
    material_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_knowledge_v2()
    try:
        revision = await register_material_source(
            db,
            user_id=int(current_user.id),
            material_id=int(material_id),
        )
        extractor_type = "llm" if settings.KNOWLEDGE_LLM_EXTRACTION_ENABLED else "deterministic"
        run = await create_extraction_run(
            db,
            user_id=int(current_user.id),
            source_revision_id=int(revision.id),
            extractor_type=extractor_type,
        )
        return serialize_extraction_run(run)
    except PermissionError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/extraction-runs/{run_id}")
async def get_extraction_run(
    run_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    run = await db.scalar(
        select(KnowledgeExtractionRun).where(
            KnowledgeExtractionRun.id == int(run_id),
            KnowledgeExtractionRun.user_id == int(current_user.id),
        )
    )
    if run is None:
        raise HTTPException(status_code=404, detail="Extraction Run 不存在")
    return serialize_extraction_run(run)


@router.post("/extraction-runs/{run_id}/retry")
async def retry_run(
    run_id: int,
    force: bool = False,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        run = await retry_extraction_run(
            db,
            user_id=int(current_user.id),
            run_id=int(run_id),
            force=bool(force),
        )
    except PermissionError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return serialize_extraction_run(run)


@router.post("/extraction-runs/{run_id}/cancel")
async def cancel_run(
    run_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        run = await cancel_extraction_run(
            db,
            user_id=int(current_user.id),
            run_id=int(run_id),
        )
    except PermissionError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return serialize_extraction_run(run)


@router.get("/resolution-candidates")
async def get_resolution_candidates(
    decision: str = Query(default="pending", pattern="^(pending|accepted|rejected|create_new|all)$"),
    source_type: str | None = Query(default=None, pattern="^(material|note)$"),
    source_id: int | None = Query(default=None, gt=0),
    limit: int = Query(default=100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_knowledge_v2()
    return {
        "candidates": await list_resolution_candidates(
            db,
            user_id=int(current_user.id),
            decision=decision,
            source_type=source_type,
            source_id=source_id,
            limit=limit,
        )
    }


@router.post("/resolution-candidates/{candidate_id}/resolve")
async def decide_resolution_candidate(
    candidate_id: int,
    body: ResolutionDecisionRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_knowledge_v2()
    try:
        return await resolve_candidate(
            db,
            user_id=int(current_user.id),
            candidate_id=int(candidate_id),
            action=body.action,
            concept_id=body.concept_id,
            concept_name=body.concept_name,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=404, detail=redact_sensitive_text(exc)) from exc
    except (LookupError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=redact_sensitive_text(exc)) from exc


@router.post("/projection/rebuild")
async def rebuild_knowledge_projection(
    force: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_knowledge_v2()
    row = await enqueue_user_knowledge_rebuild(
        db,
        user_id=int(current_user.id),
        force=bool(force),
    )
    return {
        "queued": True,
        "outbox_id": int(row.id),
        "status": row.status,
        "embedding_enabled": bool(settings.KNOWLEDGE_EMBEDDING_ENABLED),
    }


@router.get("/status")
async def knowledge_status(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    user_id = int(current_user.id)
    counts = {
        "sources": int(
            await db.scalar(
                select(func.count(KnowledgeSource.id)).where(
                    KnowledgeSource.user_id == user_id,
                    KnowledgeSource.status == "active",
                )
            )
            or 0
        ),
        "claims": int(
            await db.scalar(
                select(func.count(Claim.id)).where(
                    Claim.user_id == user_id,
                    Claim.lifecycle_status == "active",
                )
            )
            or 0
        ),
        "confirmed_claim_links": int(
            await db.scalar(
                select(func.count(ClaimConceptLink.id)).where(
                    ClaimConceptLink.user_id == user_id,
                    ClaimConceptLink.review_status == "confirmed",
                )
            )
            or 0
        ),
        "resolution_candidates": int(
            await db.scalar(
                select(func.count(EntityResolutionCandidate.id)).where(
                    EntityResolutionCandidate.user_id == user_id,
                )
            )
            or 0
        ),
        "pending_resolution": await pending_resolution_count(db, user_id=user_id),
    }
    return {
        "enabled": bool(settings.KNOWLEDGE_V2_ENABLED),
        "semantic_auto_resolve_enabled": False,
        "counts": counts,
        "projection": await knowledge_status_summary(db, user_id=user_id),
        "graph_runtime": await graph_runtime_status(db, user_id=user_id),
    }
