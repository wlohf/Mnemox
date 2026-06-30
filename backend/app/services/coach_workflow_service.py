"""Durable coach workflow state without autonomous writes."""
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.coach import CoachWorkflow


SUPPORTED_WORKFLOW_TYPES = {
    "weekly_review_planning",
    "exam_sprint",
    "comeback_plan",
    "guided_reflection",
}
ACTIVE_STATUSES = {"active", "paused"}
TERMINAL_STATUSES = {"completed", "cancelled"}
WORKFLOW_STEP_ORDER = {
    "weekly_review_planning": ["collect_signal", "draft_plan", "await_confirmation", "follow_up"],
    "exam_sprint": ["collect_deadline", "compress_priorities", "await_confirmation", "follow_up"],
    "comeback_plan": ["reset_scope", "draft_minimum_day", "await_confirmation", "follow_up"],
    "guided_reflection": ["acknowledge_pattern", "ask_reflection", "await_response", "follow_up"],
}


def coach_workflow_to_dict(row: CoachWorkflow) -> dict[str, Any]:
    return {
        "id": row.id,
        "user_id": row.user_id,
        "workflow_type": row.workflow_type,
        "status": row.status,
        "current_step": row.current_step,
        "state": row.state or {},
        "pending_draft": row.pending_draft,
        "last_event_id": row.last_event_id,
        "started_at": row.started_at.isoformat() if row.started_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "completed_at": row.completed_at.isoformat() if row.completed_at else None,
    }


def _initial_step(workflow_type: str) -> str:
    return WORKFLOW_STEP_ORDER.get(workflow_type, ["collect_signal"])[0]


def _append_history(state: dict[str, Any], action: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    next_state = dict(state or {})
    history = list(next_state.get("history") or [])
    history.append(
        {
            "action": action,
            "payload": payload or {},
            "at": datetime.now().isoformat(),
        }
    )
    next_state["history"] = history[-50:]
    return next_state


async def start_coach_workflow(
    db: AsyncSession,
    user_id: int,
    workflow_type: str,
    *,
    event_id: str | None = None,
    state: dict[str, Any] | None = None,
    pending_draft: dict[str, Any] | None = None,
) -> dict[str, Any]:
    workflow_type = str(workflow_type or "").strip()
    if workflow_type not in SUPPORTED_WORKFLOW_TYPES:
        raise ValueError("不支持的 Coach workflow 类型")

    result = await db.execute(
        select(CoachWorkflow)
        .where(
            CoachWorkflow.user_id == user_id,
            CoachWorkflow.workflow_type == workflow_type,
            CoachWorkflow.status.in_(ACTIVE_STATUSES),
        )
        .order_by(CoachWorkflow.updated_at.desc(), CoachWorkflow.started_at.desc())
        .limit(1)
    )
    existing = result.scalar_one_or_none()
    if existing:
        existing.last_event_id = event_id or existing.last_event_id
        existing.pending_draft = pending_draft if pending_draft is not None else existing.pending_draft
        existing.state = _append_history(existing.state or {}, "reused", {"event_id": event_id})
        existing.updated_at = datetime.now()
        await db.flush()
        await db.refresh(existing)
        return coach_workflow_to_dict(existing)

    initial_state = _append_history(state or {}, "started", {"event_id": event_id})
    row = CoachWorkflow(
        id=f"cw_{uuid4().hex[:24]}",
        user_id=user_id,
        workflow_type=workflow_type,
        status="active",
        current_step=_initial_step(workflow_type),
        state=initial_state,
        pending_draft=pending_draft,
        last_event_id=event_id,
    )
    db.add(row)
    await db.flush()
    await db.refresh(row)
    return coach_workflow_to_dict(row)


async def list_coach_workflows(
    db: AsyncSession,
    user_id: int,
    *,
    status: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    query = select(CoachWorkflow).where(CoachWorkflow.user_id == user_id)
    if status:
        query = query.where(CoachWorkflow.status == status)
    query = query.order_by(CoachWorkflow.updated_at.desc(), CoachWorkflow.started_at.desc()).limit(max(1, min(int(limit or 20), 100)))
    result = await db.execute(query)
    return [coach_workflow_to_dict(row) for row in result.scalars().all()]


async def advance_coach_workflow(
    db: AsyncSession,
    user_id: int,
    workflow_id: str,
    *,
    action: str,
    step: str | None = None,
    status: str | None = None,
    payload: dict[str, Any] | None = None,
    pending_draft: dict[str, Any] | None = None,
) -> dict[str, Any]:
    result = await db.execute(select(CoachWorkflow).where(CoachWorkflow.id == workflow_id, CoachWorkflow.user_id == user_id))
    row = result.scalar_one_or_none()
    if not row:
        raise ValueError("Coach workflow 不存在或无权访问")
    if row.status in TERMINAL_STATUSES:
        raise ValueError("Coach workflow 已结束")

    action = str(action or "advanced").strip()[:80] or "advanced"
    next_status = str(status or row.status).strip()
    if next_status not in ACTIVE_STATUSES | TERMINAL_STATUSES:
        raise ValueError("不支持的 Coach workflow 状态")

    if step:
        allowed_steps = WORKFLOW_STEP_ORDER.get(row.workflow_type, [])
        if step not in allowed_steps:
            raise ValueError("不支持的 Coach workflow 步骤")
        row.current_step = step
    elif action == "advance":
        allowed_steps = WORKFLOW_STEP_ORDER.get(row.workflow_type, [])
        if row.current_step in allowed_steps:
            index = allowed_steps.index(row.current_step)
            row.current_step = allowed_steps[min(index + 1, len(allowed_steps) - 1)]

    row.status = next_status
    row.pending_draft = pending_draft if pending_draft is not None else row.pending_draft
    row.state = _append_history(row.state or {}, action, payload)
    row.updated_at = datetime.now()
    if next_status in TERMINAL_STATUSES:
        row.completed_at = row.updated_at
    await db.flush()
    await db.refresh(row)
    return coach_workflow_to_dict(row)
