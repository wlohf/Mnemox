"""Confirmation-first execution for actions emitted by a persisted AgentKernel job."""
from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import new_job_id
from app.models.agent import AgentActionConfirmation, AgentExecutionLog, AgentJob
from app.models.goal import Goal, Task
from app.services.agent_service import _sanitize_llm_actions, remember_agent_feedback
from app.utils.utc import to_utc_iso, utc_now_db, utc_today


class KernelActionNotFound(ValueError):
    pass


class KernelActionConflict(ValueError):
    pass


def _confirmation_payload(
    confirmation: AgentActionConfirmation,
    *,
    idempotent: bool = False,
) -> dict[str, Any]:
    result = confirmation.result if isinstance(confirmation.result, dict) else None
    return {
        "draft_id": str(confirmation.id),
        "job_id": str(confirmation.job_id),
        "status": str(confirmation.status),
        "action": dict(confirmation.action_snapshot or {}),
        "draft": dict(confirmation.draft or {}),
        "requires_confirmation": (confirmation.draft or {}).get("operation") == "create_task",
        "execution_result": result,
        "idempotent": idempotent,
    }


async def _owned_actionable_kernel_job(
    db: AsyncSession,
    user_id: int,
    job_id: str,
) -> AgentJob:
    job = await db.scalar(
        select(AgentJob).where(
            AgentJob.id == job_id,
            AgentJob.user_id == user_id,
            AgentJob.agent == "kernel",
            AgentJob.scenario == "agent_kernel_v1",
        )
    )
    if job is None:
        raise KernelActionNotFound("kernel_job_not_found")
    result = job.result if isinstance(job.result, dict) else {}
    fallback = result.get("fallback") if isinstance(result.get("fallback"), dict) else {}
    is_rules_fallback = (
        job.status == "failed"
        and result.get("status") == "fallback"
        and fallback.get("source") == "rules"
        and fallback.get("available") is True
    )
    if (job.status != "completed" and not is_rules_fallback) or not result:
        raise KernelActionConflict("kernel_job_not_completed")
    return job


def _action_from_job(job: AgentJob, action_id: str) -> dict[str, Any]:
    raw_actions = (job.result or {}).get("next_actions")
    raw_sources = {
        str(item.get("id")): str(item.get("source") or "")
        for item in (raw_actions or [])
        if isinstance(item, dict) and item.get("id")
    }
    for action in _sanitize_llm_actions(raw_actions):
        source = raw_sources.get(str(action.get("id")))
        if source in {"rules", "rules_fallback", "kernel"}:
            action["source"] = source
        if str(action.get("id")) == action_id:
            return action
    raise KernelActionNotFound("kernel_action_not_found")


async def _active_goal_for_action(
    db: AsyncSession,
    user_id: int,
    action: dict[str, Any],
) -> Goal | None:
    target = action.get("target") if isinstance(action.get("target"), dict) else {}
    try:
        requested_goal_id = int(target.get("goal_id")) if target.get("goal_id") else None
    except (TypeError, ValueError):
        requested_goal_id = None
    if requested_goal_id is not None:
        goal = await db.scalar(
            select(Goal).where(
                Goal.id == requested_goal_id,
                Goal.user_id == user_id,
                Goal.status == "active",
            )
        )
        if goal is not None:
            return goal
    return await db.scalar(
        select(Goal)
        .where(Goal.user_id == user_id, Goal.status == "active")
        .order_by(Goal.deadline.is_(None), Goal.deadline, Goal.id)
        .limit(1)
    )


async def _draft_from_kernel_action(
    db: AsyncSession,
    user_id: int,
    job_id: str,
    action: dict[str, Any],
) -> dict[str, Any]:
    action_type = str(action.get("action_type") or "plan")
    writable_types = {"task", "plan", "practice", "reflect", "learn", "summarize"}
    goal = await _active_goal_for_action(db, user_id, action) if action_type in writable_types else None
    if goal is None:
        return {
            "operation": "navigate",
            "route": action.get("route") or "/agent",
            "source_job_id": job_id,
            "source_action_id": action.get("id"),
        }

    task_type = {
        "practice": "practice",
        "reflect": "summarize",
        "summarize": "summarize",
        "review": "review",
    }.get(action_type, "learn")
    return {
        "operation": "create_task",
        "goal_id": int(goal.id),
        "goal_title": str(goal.title),
        "title": str(action.get("title") or "AgentKernel 推荐任务")[:200],
        "description": str(action.get("reason") or "由 AgentKernel 根据只读证据生成。")[:1000],
        "task_type": task_type,
        "planned_date": utc_today().isoformat(),
        "estimated_minutes": int(action.get("estimated_minutes") or 15),
        "route": "/goals",
        "source_job_id": job_id,
        "source_action_id": action.get("id"),
    }


async def prepare_kernel_action_confirmation(
    db: AsyncSession,
    user_id: int,
    job_id: str,
    action_id: str,
) -> dict[str, Any]:
    job = await _owned_actionable_kernel_job(db, user_id, job_id)
    action = _action_from_job(job, action_id)
    existing = await db.scalar(
        select(AgentActionConfirmation).where(
            AgentActionConfirmation.user_id == user_id,
            AgentActionConfirmation.job_id == job_id,
            AgentActionConfirmation.action_id == action_id,
        )
    )
    if existing is not None:
        return _confirmation_payload(existing, idempotent=existing.status == "completed")

    draft = await _draft_from_kernel_action(db, user_id, job_id, action)
    confirmation = AgentActionConfirmation(
        id=new_job_id(),
        user_id=user_id,
        job_id=job_id,
        action_id=action_id,
        status="prepared",
        action_snapshot=action,
        draft=draft,
    )
    try:
        async with db.begin_nested():
            db.add(confirmation)
            await db.flush()
    except IntegrityError:
        confirmation = await db.scalar(
            select(AgentActionConfirmation).where(
                AgentActionConfirmation.user_id == user_id,
                AgentActionConfirmation.job_id == job_id,
                AgentActionConfirmation.action_id == action_id,
            )
        )
        if confirmation is None:
            raise
        return _confirmation_payload(confirmation, idempotent=confirmation.status == "completed")

    db.add(
        AgentExecutionLog(
            id=new_job_id(),
            user_id=user_id,
            job_id=job_id,
            agent="kernel",
            status="drafted",
            message=f"已准备行动草案：{action.get('title')}",
            extra_metadata={
                "draft_id": confirmation.id,
                "action_id": action_id,
                "operation": draft.get("operation"),
            },
        )
    )
    await db.flush()
    return _confirmation_payload(confirmation)


async def execute_kernel_action_confirmation(
    db: AsyncSession,
    user_id: int,
    job_id: str,
    action_id: str,
    draft_id: str,
) -> dict[str, Any]:
    confirmation = await db.scalar(
        select(AgentActionConfirmation).where(
            AgentActionConfirmation.id == draft_id,
            AgentActionConfirmation.user_id == user_id,
            AgentActionConfirmation.job_id == job_id,
            AgentActionConfirmation.action_id == action_id,
        )
    )
    if confirmation is None:
        raise KernelActionNotFound("kernel_action_draft_not_found")
    if confirmation.status == "completed":
        payload = dict(confirmation.result or {})
        payload["idempotent"] = True
        return payload
    if confirmation.status != "prepared":
        raise KernelActionConflict("kernel_action_execution_in_progress")

    job = await _owned_actionable_kernel_job(db, user_id, job_id)
    action = dict(confirmation.action_snapshot or {})
    draft = dict(confirmation.draft or {})
    operation = str(draft.get("operation") or "navigate")
    goal: Goal | None = None
    existing_task: Task | None = None
    planned_date = utc_today()
    if operation == "create_task":
        try:
            goal_id = int(draft.get("goal_id"))
            planned_date = date.fromisoformat(str(draft.get("planned_date") or "")[:10])
        except (TypeError, ValueError) as exc:
            raise KernelActionConflict("kernel_action_draft_invalid") from exc
        goal = await db.scalar(
            select(Goal).where(
                Goal.id == goal_id,
                Goal.user_id == user_id,
                Goal.status == "active",
            )
        )
        if goal is None:
            raise KernelActionConflict("kernel_action_goal_unavailable")
        existing_task = await db.scalar(
            select(Task)
            .where(
                Task.goal_id == goal_id,
                Task.title == str(draft.get("title") or "")[:200],
                Task.planned_date == planned_date,
            )
            .order_by(Task.id)
            .limit(1)
        )

    claimed_at = utc_now_db().replace(microsecond=0)
    claimed = await db.execute(
        update(AgentActionConfirmation)
        .where(
            AgentActionConfirmation.id == draft_id,
            AgentActionConfirmation.user_id == user_id,
            AgentActionConfirmation.status == "prepared",
        )
        .values(status="executing", confirmed_at=claimed_at, updated_at=claimed_at)
        .execution_options(synchronize_session=False)
    )
    if claimed.rowcount != 1:
        await db.rollback()
        confirmation = await db.scalar(
            select(AgentActionConfirmation).where(
                AgentActionConfirmation.id == draft_id,
                AgentActionConfirmation.user_id == user_id,
            )
        )
        if confirmation is not None and confirmation.status == "completed":
            payload = dict(confirmation.result or {})
            payload["idempotent"] = True
            return payload
        raise KernelActionConflict("kernel_action_execution_in_progress")
    await db.refresh(confirmation)

    created_task: dict[str, Any] | None = None
    status = "navigated"
    route = str(draft.get("route") or action.get("route") or "/agent")
    if operation == "create_task":
        task = existing_task
        if task is None:
            task = Task(
                goal_id=int(goal.id),
                title=str(draft.get("title") or "AgentKernel 推荐任务")[:200],
                description=str(draft.get("description") or "")[:1000],
                task_type=str(draft.get("task_type") or "learn")[:30],
                planned_date=planned_date,
                status="pending",
            )
            db.add(task)
            await db.flush()
            status = "created"
        else:
            status = "skipped_duplicate"
        created_task = {
            "id": int(task.id),
            "goal_id": int(task.goal_id),
            "title": task.title,
            "description": task.description,
            "task_type": task.task_type,
            "planned_date": task.planned_date.isoformat() if task.planned_date else None,
            "status": task.status,
            "route": "/goals",
        }
        route = "/goals"

    await remember_agent_feedback(
        db,
        user_id,
        action_id,
        "accepted" if status in {"created", "skipped_duplicate"} else "navigated",
        f"来自 AgentKernel 任务 {job_id} 的确认行动",
        0.8 if status == "created" else None,
        action,
    )
    result = {
        "status": status,
        "job_id": job_id,
        "draft_id": draft_id,
        "action": action,
        "draft": draft,
        "created_task": created_task,
        "route": route,
        "idempotent": False,
    }
    confirmation.status = "completed"
    confirmation.result = result
    confirmation.updated_at = utc_now_db()

    stored_job_result = dict(job.result or {})
    executions = (
        dict(stored_job_result.get("action_executions"))
        if isinstance(stored_job_result.get("action_executions"), dict)
        else {}
    )
    executions[action_id] = {
        "status": status,
        "draft_id": draft_id,
        "task_id": created_task.get("id") if created_task else None,
        "confirmed_at": to_utc_iso(claimed_at),
    }
    stored_job_result["action_executions"] = executions
    job.result = stored_job_result
    db.add(
        AgentExecutionLog(
            id=new_job_id(),
            user_id=user_id,
            job_id=job_id,
            agent="kernel",
            status="confirmed",
            message=(
                f"用户已确认行动并创建任务：{created_task.get('title')}"
                if status == "created" and created_task
                else f"用户已确认行动：{action.get('title')}"
            ),
            extra_metadata={
                "draft_id": draft_id,
                "action_id": action_id,
                "operation": operation,
                "result_status": status,
            },
        )
    )
    await db.flush()
    return result
