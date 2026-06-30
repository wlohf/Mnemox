"""Autonomous coach runtime API."""
from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models.user import User
from app.services.coach_action_service import create_coach_nudge, list_coach_nudges, mark_coach_nudge_shown
from app.services.coach_event_service import get_coach_event, list_recent_coach_events, record_coach_event
from app.services.coach_feedback_service import list_recent_coach_feedback, record_coach_feedback
from app.services.coach_learning_service import get_policy_skill_stats, list_skill_stats
from app.services.coach_policy_engine import evaluate_coach_policy
from app.services.coach_preference_service import get_or_create_coach_preferences, update_coach_preferences
from app.services.coach_skills.base import CoachSkillContext
from app.services.coach_skills.registry import coach_skill_registry
from app.services.coach_context_retriever import retrieve_coach_context
from app.services.coach_workflow_service import advance_coach_workflow, list_coach_workflows, start_coach_workflow
from app.services.learning_snapshot_service import build_learning_snapshot

router = APIRouter()


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
        "completed",
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
    quiet_hours_start: str | None = None
    quiet_hours_end: str | None = None
    max_nudges_per_day: int | None = None
    min_minutes_between_nudges: int | None = None
    allowed_channels: list[str] | None = None
    disabled_skill_ids: list[str] | None = None


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
        raise HTTPException(status_code=400, detail=str(exc)) from exc


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

    snapshot = await build_learning_snapshot(
        db,
        user_id,
        include_recent_notes=body.include_recent_notes,
        include_memories=body.include_memories,
    )
    preferences = await get_or_create_coach_preferences(db, user_id)
    recent_feedback = await list_recent_coach_feedback(db, user_id, limit=30)
    skill_stats = await get_policy_skill_stats(db, user_id)
    policy = evaluate_coach_policy(event, snapshot, preferences, recent_feedback, skill_stats)
    if not policy.get("should_intervene"):
        return {"nudge": None, "policy": policy, "event": event}

    skill_id = str(policy.get("skill_id") or "")
    skill = coach_skill_registry.get(skill_id)
    if not skill:
        raise HTTPException(status_code=500, detail="Coach skill 未注册")

    coach_context = await retrieve_coach_context(db, user_id, event, snapshot)
    snapshot["coach_context"] = coach_context

    result = await skill.generate(
        CoachSkillContext(
            user_id=user_id,
            event=event,
            snapshot=snapshot,
            policy=policy,
            recent_feedback=recent_feedback,
        )
    )
    nudge = await create_coach_nudge(
        db,
        user_id,
        event_id=event.get("id"),
        skill_id=skill_id,
        policy=policy,
        result=result,
    )
    return {"nudge": nudge, "policy": policy, "event": event}


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


@router.post("/nudges/{nudge_id}/feedback")
async def feedback_nudge(
    nudge_id: str,
    body: CoachFeedbackRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        return await record_coach_feedback(db, int(current_user.id), nudge_id, body.outcome, body.notes)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


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
        raise HTTPException(status_code=400, detail=str(exc)) from exc


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
        raise HTTPException(status_code=400, detail=str(exc)) from exc
