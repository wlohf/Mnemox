"""User-scoped learner state, evidence history, correction and replay APIs."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.config import settings
from app.database import get_db
from app.models.concept import Concept
from app.models.learner_model import LearnerEvidence
from app.models.user import User
from app.services.learner_model_service import (
    apply_manual_override,
    get_concept_state,
    record_evidence,
    recompute_concept_state,
)
from app.services.learning_event_service import record_learning_event
from app.services.learning_recommendation_service import list_learning_recommendations
from app.utils.error_safety import redact_sensitive_text
from app.services.projection_outbox_service import (
    list_dead_letter_tasks,
    process_outbox,
    replay_projections,
    retry_dead_letter_task,
)

router = APIRouter()


def _naive_local(value: datetime | None) -> datetime | None:
    if value is None or value.tzinfo is None:
        return value
    return value.astimezone().replace(tzinfo=None)


class ManualOverrideRequest(BaseModel):
    mastery_estimate: float | None = Field(default=None, ge=0, le=100)
    confidence: float | None = Field(default=None, ge=0, le=1)
    forgetting_risk: float | None = Field(default=None, ge=0, le=1)
    reason: str = Field(min_length=1, max_length=500)
    occurred_at: datetime | None = None


class ReplayRequest(BaseModel):
    concept_id: int | None = Field(default=None, gt=0)
    start_at: datetime | None = None
    end_at: datetime | None = None
    reset_processed: bool = True


class LearnerEvidenceRequest(BaseModel):
    evidence_type: Literal[
        "answer", "recall", "explanation", "application", "hint_count",
        "review_result", "study_duration", "study_frequency", "repeated_question",
        "interruption", "recovery",
    ]
    score: float = Field(ge=0, le=1)
    reliability: float = Field(default=0.85, ge=0, le=1)
    dimension: str | None = Field(default=None, max_length=40)
    source_type: str = Field(default="practice", min_length=1, max_length=40)
    source_id: str | None = Field(default=None, max_length=160)
    dedupe_key: str | None = Field(default=None, max_length=160)
    observed_at: datetime | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class BatchRecomputeRequest(BaseModel):
    concept_ids: list[int] | None = Field(default=None, min_length=1, max_length=500)
    as_of: datetime | None = None

    @field_validator("concept_ids")
    @classmethod
    def validate_concept_ids(cls, value: list[int] | None) -> list[int] | None:
        if value is not None and any(int(item) <= 0 for item in value):
            raise ValueError("concept_ids 必须全部为正整数")
        return value


def _owned_concept_query(user_id: int, concept_id: int):
    return select(Concept.id).where(Concept.id == int(concept_id), Concept.user_id == int(user_id))


async def _ensure_owned(db: AsyncSession, user_id: int, concept_id: int) -> None:
    if await db.scalar(_owned_concept_query(user_id, concept_id)) is None:
        raise HTTPException(status_code=404, detail="概念不存在")


def _validated_range(
    start_at: datetime | None,
    end_at: datetime | None,
) -> tuple[datetime | None, datetime | None]:
    if start_at and end_at and (start_at.tzinfo is None) != (end_at.tzinfo is None):
        raise HTTPException(status_code=422, detail="start_at 和 end_at 必须使用一致的时区格式")
    normalized_start = _naive_local(start_at)
    normalized_end = _naive_local(end_at)
    if normalized_start and normalized_end and normalized_start > normalized_end:
        raise HTTPException(status_code=422, detail="start_at 不能晚于 end_at")
    return normalized_start, normalized_end


@router.get("/concepts/{concept_id}/state")
async def concept_state(
    concept_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    try:
        return await get_concept_state(db, int(current_user.id), concept_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=redact_sensitive_text(exc)) from exc


@router.get("/recommendations")
async def learning_recommendations(
    limit: int = Query(10, ge=1, le=50),
    as_of: datetime | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    return await list_learning_recommendations(db, int(current_user.id), limit=limit, as_of=as_of)


@router.get("/concepts/{concept_id}/evidence")
async def concept_evidence(
    concept_id: int,
    offset: int = Query(0, ge=0, le=1_000_000),
    limit: int = Query(50, ge=1, le=200),
    evidence_category: Literal["direct", "indirect", "manual", "legacy"] | None = Query(None),
    evidence_type: Literal[
        "answer", "recall", "explanation", "application", "hint_count",
        "review_result", "study_duration", "study_frequency", "repeated_question",
        "interruption", "recovery", "legacy_mastery", "manual_override",
    ] | None = Query(None),
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    user_id = int(current_user.id)
    await _ensure_owned(db, user_id, concept_id)
    start_at, end_at = _validated_range(start_at, end_at)
    predicates = [LearnerEvidence.user_id == user_id, LearnerEvidence.concept_id == concept_id]
    if evidence_category:
        predicates.append(LearnerEvidence.evidence_category == evidence_category)
    if evidence_type:
        predicates.append(LearnerEvidence.evidence_type == evidence_type)
    if start_at:
        predicates.append(LearnerEvidence.observed_at >= start_at)
    if end_at:
        predicates.append(LearnerEvidence.observed_at <= end_at)
    total = await db.scalar(select(func.count()).select_from(LearnerEvidence).where(*predicates))
    rows = (
        await db.execute(
            select(LearnerEvidence)
            .where(*predicates)
            .order_by(LearnerEvidence.observed_at.desc(), LearnerEvidence.id.desc())
            .offset(offset)
            .limit(limit)
        )
    ).scalars().all()
    return {
        "items": [
            {
                "id": row.id,
                "user_id": row.user_id,
                "concept_id": row.concept_id,
                "evidence_type": row.evidence_type,
                "evidence_category": row.evidence_category,
                "dimension": row.dimension,
                "score": float(row.score),
                "reliability": float(row.reliability),
                "source_event_id": row.source_event_id,
                "source_type": row.source_type,
                "source_id": row.source_id,
                "observed_at": row.observed_at.isoformat() if row.observed_at else None,
                "model_version": row.model_version,
                "payload_version": row.payload_version,
                "payload": row.payload or {},
            }
            for row in rows
        ],
        "total": int(total or 0),
        "offset": offset,
        "limit": limit,
    }


@router.post("/concepts/{concept_id}/evidence")
async def add_concept_evidence(
    concept_id: int,
    body: LearnerEvidenceRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    user_id = int(current_user.id)
    await _ensure_owned(db, user_id, concept_id)
    event_mapping = {
        "answer": "practice.answer",
        "recall": "practice.recall",
        "explanation": "practice.explanation",
        "application": "practice.application",
        "hint_count": "practice.hint",
        "review_result": "practice.review_result",
        "study_duration": "study.duration",
        "study_frequency": "study.frequency",
        "repeated_question": "study.repeated_question",
        "interruption": "study.interruption",
        "recovery": "study.recovery",
    }
    payload = dict(body.payload)
    payload.update({"concept_id": concept_id, "score": body.score})
    event = await record_learning_event(
        db, user_id, event_mapping[body.evidence_type], source=body.source_type,
        payload=payload, dedupe_key=body.dedupe_key, occurred_at=body.observed_at,
    )
    try:
        return await record_evidence(
            db, user_id, concept_id, body.evidence_type, score=body.score,
            reliability=body.reliability, source_event_id=int(event["id"]),
            source_type=body.source_type, source_id=body.source_id, dimension=body.dimension,
            observed_at=body.observed_at, payload=payload,
        )
    except (LookupError, ValueError) as exc:
        raise HTTPException(
            status_code=404 if isinstance(exc, LookupError) else 422,
            detail=redact_sensitive_text(exc),
        ) from exc


@router.post("/concepts/{concept_id}/override")
async def set_concept_override(
    concept_id: int,
    body: ManualOverrideRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    try:
        return await apply_manual_override(
            db, int(current_user.id), concept_id,
            mastery_estimate=body.mastery_estimate, confidence=body.confidence,
            forgetting_risk=body.forgetting_risk, reason=body.reason,
            occurred_at=body.occurred_at,
            max_projection_attempts=settings.OUTBOX_WORKER_MAX_ATTEMPTS,
            retry_policy_version=settings.OUTBOX_WORKER_RETRY_POLICY_VERSION,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=redact_sensitive_text(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=redact_sensitive_text(exc)) from exc


@router.delete("/concepts/{concept_id}/override")
async def clear_concept_override(
    concept_id: int,
    reason: str = Query("用户撤销人工修正", min_length=1, max_length=500),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    try:
        return await apply_manual_override(
            db,
            int(current_user.id),
            concept_id,
            mastery_estimate=None,
            reason=reason,
            max_projection_attempts=settings.OUTBOX_WORKER_MAX_ATTEMPTS,
            retry_policy_version=settings.OUTBOX_WORKER_RETRY_POLICY_VERSION,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=redact_sensitive_text(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=redact_sensitive_text(exc)) from exc


@router.post("/concepts/{concept_id}/recompute")
async def recompute_concept(
    concept_id: int,
    as_of: datetime | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    try:
        return await recompute_concept_state(
            db,
            int(current_user.id),
            concept_id,
            as_of=as_of,
            persist=as_of is None,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=redact_sensitive_text(exc)) from exc


@router.post("/replay")
async def replay(
    body: ReplayRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    start_at, end_at = _validated_range(body.start_at, body.end_at)
    if body.concept_id is not None:
        await _ensure_owned(db, int(current_user.id), body.concept_id)
    try:
        return await replay_projections(
            db, int(current_user.id), concept_id=body.concept_id,
            start_at=start_at, end_at=end_at,
            reset_processed=body.reset_processed,
            max_attempts=settings.OUTBOX_WORKER_MAX_ATTEMPTS,
            retry_policy_version=settings.OUTBOX_WORKER_RETRY_POLICY_VERSION,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=redact_sensitive_text(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=redact_sensitive_text(exc)) from exc


@router.post("/recompute")
async def recompute_batch(
    body: BatchRecomputeRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    user_id = int(current_user.id)
    requested = sorted({int(value) for value in (body.concept_ids or []) if int(value) > 0})
    if not requested:
        total_concepts = await db.scalar(
            select(func.count()).select_from(Concept).where(Concept.user_id == user_id)
        )
        if int(total_concepts or 0) > 500:
            raise HTTPException(
                status_code=422,
                detail="未指定 concept_ids 时最多重算 500 个概念；请分批提供 concept_ids",
            )
    query = select(Concept.id).where(Concept.user_id == user_id)
    if requested:
        query = query.where(Concept.id.in_(requested))
    owned_ids = list((await db.execute(query.order_by(Concept.id.asc()).limit(500))).scalars().all())
    if requested and set(owned_ids) != set(requested):
        # Use one 404 response for missing and cross-user ids to avoid revealing
        # whether a concept exists for somebody else.
        raise HTTPException(status_code=404, detail="概念不存在")
    states = [
        await recompute_concept_state(
            db,
            user_id,
            int(concept_id),
            as_of=body.as_of,
            persist=body.as_of is None,
        )
        for concept_id in owned_ids
    ]
    return {"items": states, "count": len(states), "as_of": body.as_of.isoformat() if body.as_of else None}


@router.post("/outbox/process")
async def process(
    limit: int = Query(50, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    return await process_outbox(
        db,
        limit=limit,
        user_id=int(current_user.id),
        max_attempts=settings.OUTBOX_WORKER_MAX_ATTEMPTS,
        retry_policy_version=settings.OUTBOX_WORKER_RETRY_POLICY_VERSION,
    )


@router.get("/outbox/failures")
async def outbox_failed_tasks(
    offset: int = Query(0, ge=0, le=1_000_000),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Expose only the caller's terminal projection failures for recovery."""
    return await list_dead_letter_tasks(
        db,
        int(current_user.id),
        max_attempts=settings.OUTBOX_WORKER_MAX_ATTEMPTS,
        retry_policy_version=settings.OUTBOX_WORKER_RETRY_POLICY_VERSION,
        offset=offset,
        limit=limit,
    )


@router.post("/outbox/failures/{outbox_id}/retry")
async def retry_outbox_failed_task(
    outbox_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Explicitly requeue one owned terminal failure after user intervention."""
    try:
        return await retry_dead_letter_task(
            db,
            int(current_user.id),
            outbox_id,
            max_attempts=settings.OUTBOX_WORKER_MAX_ATTEMPTS,
            retry_policy_version=settings.OUTBOX_WORKER_RETRY_POLICY_VERSION,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="投影任务不存在") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=redact_sensitive_text(exc)) from exc
