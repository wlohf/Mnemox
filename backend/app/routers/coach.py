"""Autonomous coach runtime API."""
from __future__ import annotations

import logging
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models.user import User
from app.models.coach import CoachNudge
from app.services.coach_action_service import coach_nudge_to_dict, list_coach_nudges, mark_coach_nudge_shown
from app.services.coach_action_attempt_service import (
    ACTIVE_ATTEMPT_STATUSES,
    bind_coach_attempt_to_domain_event,
    get_coach_action_attempt,
    get_coach_nudge_replay,
    list_coach_action_attempts,
    start_coach_action_attempt,
)
from app.services.coach_event_service import get_coach_event, list_recent_coach_events, record_coach_event
from app.services.coach_feedback_service import record_coach_feedback
from app.services.coach_learning_service import list_skill_stats
from app.services.coach_preference_service import get_or_create_coach_preferences, update_coach_preferences
from app.services.coach_skills.registry import coach_skill_registry
from app.services.coach_runtime_service import evaluate_coach_event
from app.services.coach_time_service import normalize_coach_time_zone, parse_quiet_hour
from app.services.coach_workflow_service import advance_coach_workflow, list_coach_workflows, start_coach_workflow
from app.services.learning_event_service import record_learning_event
from app.services.agent_service import execute_agent_write_draft
from app.services.note_quote_service import attach_note_quote_feedback
from app.utils.error_safety import redact_sensitive_text, safe_exception_summary

router = APIRouter()
logger = logging.getLogger(__name__)

class CoachEventCreateRequest(BaseModel):
    event_type: str = Field(..., max_length=100)
    source: str = Field("frontend", max_length=50)
    channel: str | None = Field(None, max_length=40)
    payload: dict[str, Any] = Field(default_factory=dict)
    severity: str = Field("info", max_length=20)
    dedupe_key: str | None = Field(None, max_length=160)


class CoachEvaluateRequest(BaseModel):
    event_id: str | None = None
    event: CoachEventCreateRequest | None = None
    include_recent_notes: bool = True
    include_memories: bool = True


class CoachFeedbackRequest(BaseModel):
    outcome: Literal[
        "helpful",
        "accepted",
        "started",
        "completed",
        "abandoned",
        "later",
        "snoozed",
        "dismissed",
        "too_disruptive",
        "too_hard",
        "too_easy",
        "irrelevant",
        "not_my_style",
    ]
    notes: str | None = None


class CoachPreferencePatch(BaseModel):
    enabled: bool | None = None
    proactive_enabled: bool | None = None
    desktop_notifications_enabled: bool | None = None
    time_zone: str | None = Field(None, max_length=64)
    quiet_hours_start: str | None = None
    quiet_hours_end: str | None = None
    max_nudges_per_day: int | None = None
    min_minutes_between_nudges: int | None = None
    allowed_channels: list[str] | None = None
    disabled_skill_ids: list[str] | None = None

    @field_validator("time_zone")
    @classmethod
    def validate_time_zone(cls, value: str | None) -> str | None:
        return normalize_coach_time_zone(value) if value is not None else None

    @field_validator("quiet_hours_start", "quiet_hours_end")
    @classmethod
    def validate_quiet_hour(cls, value: str | None) -> str | None:
        parsed = parse_quiet_hour(value)
        return parsed.strftime("%H:%M") if parsed else None


class CoachWorkflowStartRequest(BaseModel):
    workflow_type: Literal["weekly_review_planning", "exam_sprint", "comeback_plan", "guided_reflection"]
    event_id: str | None = None
    state: dict[str, Any] = Field(default_factory=dict)
    pending_draft: dict[str, Any] | None = None


class CoachWorkflowAdvanceRequest(BaseModel):
    action: str = Field("advance", max_length=80)
    step: str | None = Field(None, max_length=80)
    status: Literal["active", "paused", "completed", "cancelled"] | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    pending_draft: dict[str, Any] | None = None


class CoachDraftConfirmRequest(BaseModel):
    attempt_id: str = Field(..., min_length=1, max_length=40)


@router.post("/events")
async def create_event(
    body: CoachEventCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        return await record_coach_event(
            db,
            int(current_user.id),
            body.event_type,
            body.source,
            body.payload,
            body.severity,
            dedupe_key=body.dedupe_key,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=redact_sensitive_text(exc)) from exc


@router.get("/events")
async def list_events(
    limit: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await list_recent_coach_events(db, int(current_user.id), limit=limit)


@router.post("/evaluate")
async def evaluate_coach(
    body: CoachEvaluateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    user_id = int(current_user.id)
    event: dict[str, Any] | None = None
    if body.event_id:
        event = await get_coach_event(db, user_id, body.event_id)
        if not event:
            raise HTTPException(status_code=404, detail="Coach event 不存在")
    elif body.event:
        event = await record_coach_event(
            db,
            user_id,
            body.event.event_type,
            body.event.source,
            body.event.payload,
            body.event.severity,
            dedupe_key=body.event.dedupe_key,
        )
        if body.event.channel:
            event["channel"] = body.event.channel
    else:
        event = {
            "id": None,
            "user_id": user_id,
            "event_type": "app.evaluate",
            "source": "frontend",
            "severity": "info",
            "payload": {},
        }

    try:
        return await evaluate_coach_event(
            db,
            user_id,
            event,
            include_recent_notes=body.include_recent_notes,
            include_memories=body.include_memories,
        )
    except ValueError as exc:
        raise HTTPException(status_code=500, detail=redact_sensitive_text(exc)) from exc


@router.get("/nudges")
async def get_nudges(
    status: str | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await list_coach_nudges(db, int(current_user.id), status=status, limit=limit)


@router.get("/learning/stats")
async def get_learning_stats(
    limit: int = Query(100, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await list_skill_stats(db, int(current_user.id), limit=limit)


@router.post("/nudges/{nudge_id}/shown")
async def mark_nudge_shown(
    nudge_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    nudge = await mark_coach_nudge_shown(db, int(current_user.id), nudge_id)
    if not nudge:
        raise HTTPException(status_code=404, detail="Coach nudge 不存在")
    return nudge


@router.post("/nudges/{nudge_id}/start")
async def start_nudge_action(
    nudge_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Record intent to act, then let the target domain confirm the outcome."""

    try:
        return await start_coach_action_attempt(db, int(current_user.id), nudge_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=redact_sensitive_text(exc)) from exc


@router.get("/nudges/{nudge_id}/attempts")
async def get_nudge_attempts(
    nudge_id: str,
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await list_coach_action_attempts(
        db,
        int(current_user.id),
        nudge_id=nudge_id,
        limit=limit,
    )


@router.get("/nudges/{nudge_id}/replay")
async def replay_nudge(
    nudge_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    replay = await get_coach_nudge_replay(db, int(current_user.id), nudge_id)
    if not replay:
        raise HTTPException(status_code=404, detail="Coach nudge 不存在")
    return replay


@router.get("/nudges/{nudge_id}/draft")
async def get_nudge_draft(
    nudge_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    nudge = await db.scalar(
        select(CoachNudge).where(
            CoachNudge.id == nudge_id,
            CoachNudge.user_id == int(current_user.id),
        )
    )
    if not nudge:
        raise HTTPException(status_code=404, detail="Coach nudge 不存在")
    if not nudge.requires_confirmation or not isinstance(nudge.draft, dict):
        raise HTTPException(status_code=400, detail="这条 Coach 建议没有待确认草案")
    return {
        "nudge": coach_nudge_to_dict(nudge),
        "draft": nudge.draft,
    }


@router.post("/nudges/{nudge_id}/draft/confirm")
async def confirm_nudge_draft(
    nudge_id: str,
    body: CoachDraftConfirmRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Execute only a displayed Coach plan draft after explicit confirmation."""

    user_id = int(current_user.id)
    nudge = await db.scalar(
        select(CoachNudge).where(CoachNudge.id == nudge_id, CoachNudge.user_id == user_id)
    )
    if not nudge:
        raise HTTPException(status_code=404, detail="Coach nudge 不存在")
    if not nudge.requires_confirmation or not isinstance(nudge.draft, dict):
        raise HTTPException(status_code=400, detail="这条 Coach 建议没有可确认草案")
    if str((nudge.suggested_action or {}).get("type") or "") != "create_daily_plan_draft":
        raise HTTPException(status_code=400, detail="暂不支持确认这种 Coach 草案")

    attempt = await get_coach_action_attempt(db, user_id, body.attempt_id)
    if not attempt or attempt.nudge_id != nudge.id or attempt.status not in ACTIVE_ATTEMPT_STATUSES:
        raise HTTPException(status_code=400, detail="Coach 行动尝试不可用")

    intent = str(nudge.draft.get("intent") or "")
    if intent != "add_daily_plan_items":
        raise HTTPException(status_code=400, detail="Coach 草案类型不匹配")
    try:
        result = await execute_agent_write_draft(db, user_id, intent, nudge.draft)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=redact_sensitive_text(exc)) from exc

    created = result.get("created") or {}
    plan = created.get("plan") or {}
    domain_event = await record_learning_event(
        db,
        user_id,
        "daily_plan.updated",
        source="coach_draft_confirmation",
        payload={
            "date": plan.get("date") or nudge.draft.get("date"),
            "item_count": len(created.get("items") or []),
            "coach_nudge_id": nudge.id,
            "coach_action_attempt_id": attempt.id,
        },
        dedupe_key=f"coach:daily_plan.confirmed:{attempt.id}",
    )
    try:
        attribution = await bind_coach_attempt_to_domain_event(
            db,
            user_id,
            attempt.id,
            event_id=int(domain_event["id"]),
            event_type="daily_plan.updated",
            outcome="completed",
            reason="draft_confirmed",
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=redact_sensitive_text(exc)) from exc
    return {"ok": True, "result": result, "attribution": attribution}


@router.post("/nudges/{nudge_id}/feedback")
async def feedback_nudge(
    nudge_id: str,
    body: CoachFeedbackRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        feedback = await record_coach_feedback(db, int(current_user.id), nudge_id, body.outcome, body.notes)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=redact_sensitive_text(exc)) from exc

    try:
        await attach_note_quote_feedback(db, int(current_user.id), nudge_id, body.outcome)
    except Exception as exc:  # 引用反馈回写失败不影响反馈主流程
        logger.warning(
            "笔记自引反馈回写失败 nudge_id=%s err=%s",
            nudge_id,
            safe_exception_summary(exc),
        )
    return feedback


@router.get("/skills")
async def get_skills(
    current_user: User = Depends(get_current_user),
):
    return coach_skill_registry.list()


@router.get("/preferences")
async def get_preferences(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await get_or_create_coach_preferences(db, int(current_user.id))


@router.patch("/preferences")
async def patch_preferences(
    body: CoachPreferencePatch,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    patch = body.model_dump(exclude_unset=True)
    return await update_coach_preferences(db, int(current_user.id), patch)


@router.post("/workflows")
async def create_workflow(
    body: CoachWorkflowStartRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        return await start_coach_workflow(
            db,
            int(current_user.id),
            body.workflow_type,
            event_id=body.event_id,
            state=body.state,
            pending_draft=body.pending_draft,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=redact_sensitive_text(exc)) from exc


@router.get("/workflows")
async def get_workflows(
    status: str | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await list_coach_workflows(db, int(current_user.id), status=status, limit=limit)


@router.patch("/workflows/{workflow_id}")
async def advance_workflow(
    workflow_id: str,
    body: CoachWorkflowAdvanceRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        return await advance_coach_workflow(
            db,
            int(current_user.id),
            workflow_id,
            action=body.action,
            step=body.step,
            status=body.status,
            payload=body.payload,
            pending_draft=body.pending_draft,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=redact_sensitive_text(exc)) from exc
