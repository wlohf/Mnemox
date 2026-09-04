"""自主学习 Agent 路由"""
import asyncio
import json
import logging
from time import monotonic
from datetime import timedelta
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.config import settings
from app.database import async_session_maker, get_db
from app.agents.agent_kernel import run_agent_kernel
from app.agents.base import new_job_id
from app.agents.manager import agent_manager
from app.models.agent import AgentExecutionLog, AgentJob
from app.models.user import User
from app.services.agent_service import (
    build_agent_action_draft,
    build_agent_brief,
    build_agent_prompt_snippet,
    build_agent_write_draft,
    execute_agent_action,
    execute_agent_write_draft,
    collect_agent_profile_control_logs,
    remember_agent_feedback,
    update_agent_profile_item,
)
from app.services.goal_context_service import build_goal_context
from app.services.learning_event_service import record_learning_event
from app.services.weekly_learning_report_service import build_weekly_learning_report
from app.services.coach_preference_service import get_or_create_coach_preferences
from app.services.agent_kernel_action_service import (
    KernelActionConflict,
    KernelActionNotFound,
    execute_kernel_action_confirmation,
    prepare_kernel_action_confirmation,
)
from app.services.agent_budget_service import (
    AgentKernelRunConflict,
    checkpoint_usage,
    daily_budget_after_run,
    get_agent_kernel_daily_budget,
    lock_agent_kernel_run_slot,
)
from app.utils.error_safety import redact_sensitive_text, safe_exception_summary
from app.utils.utc import utc_now_db

router = APIRouter()
logger = logging.getLogger(__name__)

AGENT_JOB_EVENT_POLL_SECONDS = 0.5
AGENT_JOB_EVENT_HEARTBEAT_SECONDS = 15.0
AGENT_JOB_EVENT_MAX_SECONDS = 300.0
AGENT_JOB_TERMINAL_STATUSES = {"completed", "failed", "cancelled", "skipped"}


class AgentAction(BaseModel):
    id: str
    title: str
    reason: str
    action_type: str
    priority: Literal["high", "medium", "low"]
    estimated_minutes: int
    route: str
    target: Any = None
    source: str | None = None
    explainability: dict[str, Any] | None = None


class AgentBriefResponse(BaseModel):
    date: str
    generated_at: str
    autonomy_level: str
    readiness_score: float
    risk_level: Literal["low", "medium", "high"]
    state_summary: str
    current_focus: str
    next_actions: list[AgentAction]
    watch_signals: list[str]
    planner: dict[str, Any] | None = None
    context: dict[str, Any]


class AgentActionDraftResponse(BaseModel):
    action: AgentAction
    draft: dict[str, Any]
    requires_confirmation: bool


class AgentActionExecuteResponse(BaseModel):
    status: str
    action: AgentAction
    draft: dict[str, Any]
    created_task: dict[str, Any] | None = None
    route: str | None = None


class AgentWriteDraftRequest(BaseModel):
    message: str


class AgentWriteExecuteRequest(BaseModel):
    intent: Literal["create_note", "create_goal_tasks", "add_daily_plan_items"]
    draft: dict[str, Any]


class AgentGoalActionDraftRequest(BaseModel):
    message: str | None = None


class AgentTaskTriggerRequest(BaseModel):
    agent: Literal["study_plan", "review", "chat"]
    task: str | None = "run"
    payload: dict[str, Any] | None = None


class AgentToolCallRequest(BaseModel):
    tool: Literal[
        "search_notes",
        "search_materials",
        "search_wrong_questions",
        "search_memories",
        "search_concepts",
        "search_learner_state",
        "get_profile",
        "get_agent_learning_profile",
        "get_today_tasks",
        "get_recent_feedback",
    ]
    query: str | None = None
    limit: int | None = 5


class AgentFeedbackRequest(BaseModel):
    outcome: Literal[
        "accepted",
        "dismissed",
        "completed",
        "failed",
        "adjusted",
        "later",
        "useless",
        "helpful",
        "rejected",
        "snoozed",
    ]
    notes: str | None = None
    effectiveness: float | None = None
    reason_code: Literal[
        "too_long",
        "too_late",
        "too_easy",
        "too_hard",
        "too_disruptive",
        "irrelevant_to_goal",
        "already_known",
        "other",
    ] | None = None


class AgentProfileControlRequest(BaseModel):
    operation: Literal["ignore", "inaccurate", "lock", "unlock", "restore"]


@router.get("/status")
async def get_agent_status(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """查询 Agent runtime 状态、任务队列和执行日志。"""
    user_id = int(current_user.id)
    status = await agent_manager.status(db, user_id)
    status["profile_control_logs"] = await collect_agent_profile_control_logs(db, user_id, limit=12)
    status["kernel_daily_budget"] = await get_agent_kernel_daily_budget(
        db,
        user_id,
        model_call_limit=settings.AGENT_KERNEL_DAILY_MODEL_CALLS_PER_USER,
        estimated_token_limit=settings.AGENT_KERNEL_DAILY_ESTIMATED_TOKENS_PER_USER,
    )
    return status


@router.get("/runtime/proactive-status")
async def get_proactive_runtime_status(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Expose the opted-in review-debt scanner without exposing other users.

    The worker itself is deployment-scoped, while the choice to be scanned is
    per learner.  Keeping both states in one response lets the UI explain why
    a saved preference may not run in a local SQLite session.
    """
    preference = await get_or_create_coach_preferences(db, int(current_user.id))
    worker = getattr(request.app.state, "agent_runtime_worker", None)
    if worker is None:
        return {
            "preference": preference,
            "scheduler": {
                "available": False,
                "running": False,
                "message": "当前运行模式不会启动后台定时检查；你仍可在页面内按现有 Coach 设置触发评估。",
            },
        }

    snapshot = worker.snapshot()
    running = bool(snapshot.get("running"))
    return {
        "preference": preference,
        "scheduler": {
            "available": True,
            "running": running,
            "poll_interval_seconds": snapshot.get("poll_interval_seconds"),
            "user_interval_seconds": snapshot.get("user_interval_seconds"),
            "retry_interval_seconds": snapshot.get("retry_interval_seconds"),
            "user_timeout_seconds": snapshot.get("user_timeout_seconds"),
            "quiet_hours_deferred": snapshot.get("quiet_hours_deferred"),
            "timed_out_users": snapshot.get("timed_out_users"),
            "last_run_at": snapshot.get("last_run_at"),
            "last_success_at": snapshot.get("last_success_at"),
            "last_error_at": snapshot.get("last_error_at"),
            "message": (
                "后台会低频检查复习积压，只在 Agent 面板准备可选建议，不会自动修改计划或开始学习。"
                if running
                else "后台检查器暂未运行；你的偏好已保留，恢复后才会继续检查。"
            ),
        },
    }


class AgentKernelRunRequest(BaseModel):
    objective: str | None = None
    max_steps: int = 6
    resume_from_job_id: str | None = None
    prepared_job_id: str | None = None


class AgentKernelActionConfirmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    draft_id: str = Field(min_length=1, max_length=32)


def _kernel_step_payload(step: Any) -> dict[str, Any]:
    return {
        "index": step.index,
        "kind": step.kind,
        "tool": step.tool,
        "args": step.args,
        "thought": step.thought,
        "observation_preview": step.observation_preview,
    }


def _checkpoint_step_index(checkpoint: Any) -> int | None:
    if (
        not isinstance(checkpoint, dict)
        or checkpoint.get("version") != 1
        or not isinstance(checkpoint.get("messages"), list)
        or not checkpoint.get("messages")
    ):
        return None
    try:
        return max(0, int(checkpoint.get("next_step_index") or 1) - 1)
    except (TypeError, ValueError):
        return None


def _bounded_kernel_max_steps(value: Any, fallback: int = 6) -> int:
    try:
        return max(1, min(int(value or fallback), 8))
    except (TypeError, ValueError):
        return max(1, min(int(fallback), 8))


def _kernel_response_from_job(job: AgentJob) -> dict[str, Any]:
    stored = job.result if isinstance(job.result, dict) else {}
    stored_status = str(stored.get("status") or "")
    status = (
        stored_status
        if stored_status in {"completed", "fallback", "failed", "cancelled", "unavailable"}
        else job.status
    )
    return {
        "status": status,
        "reason": stored.get("reason"),
        "strategy": stored.get("strategy"),
        "fallback_plan": stored.get("fallback_plan"),
        "next_actions": stored.get("next_actions") if isinstance(stored.get("next_actions"), list) else [],
        "steps": stored.get("steps") if isinstance(stored.get("steps"), list) else [],
        "error": stored.get("error"),
        "usage": stored.get("usage") if isinstance(stored.get("usage"), dict) else {},
        "fallback": stored.get("fallback") if isinstance(stored.get("fallback"), dict) else None,
        "job_id": str(job.id),
    }


async def _build_kernel_rules_fallback(
    db: AsyncSession,
    user_id: int,
    *,
    reason: str,
) -> dict[str, Any]:
    """Build the stable rule brief without making another model request."""
    try:
        brief = await build_agent_brief(db, user_id, use_llm=False)
    except Exception as exc:
        logger.warning(
            "Kernel rules fallback could not be built user_id=%s reason=%s err=%s",
            user_id,
            reason,
            safe_exception_summary(exc),
        )
        return {
            "strategy": None,
            "fallback_plan": None,
            "next_actions": [],
            "fallback": {"source": "rules", "reason": reason, "available": False},
        }

    actions: list[dict[str, Any]] = []
    for raw_action in (brief.get("next_actions") or [])[:3]:
        if not isinstance(raw_action, dict):
            continue
        action = dict(raw_action)
        action["source"] = "rules_fallback"
        actions.append(action)
    current_focus = str(brief.get("current_focus") or "").strip()[:160]
    return {
        "strategy": "证据型 Kernel 暂未完成，已切换到稳定规则简报。",
        "fallback_plan": (
            f"先完成「{current_focus}」，稍后可从保留的运行记录继续。"
            if current_focus
            else "先保持最小学习节奏，稍后可从保留的运行记录继续。"
        ),
        "next_actions": actions,
        "fallback": {
            "source": "rules",
            "reason": reason,
            "available": bool(actions),
            "generated_at": brief.get("generated_at"),
            "risk_level": brief.get("risk_level"),
        },
    }


async def _owned_agent_job(db: AsyncSession, user_id: int, job_id: str) -> AgentJob:
    job = await db.scalar(
        select(AgentJob).where(AgentJob.id == job_id, AgentJob.user_id == user_id)
    )
    if job is None:
        raise HTTPException(status_code=404, detail="agent_job_not_found")
    return job


async def _prepare_kernel_job(
    db: AsyncSession,
    user_id: int,
    body: AgentKernelRunRequest,
) -> AgentJob:
    if body.prepared_job_id:
        raise HTTPException(status_code=400, detail="prepared_job_id_not_allowed")
    requested_objective = str(body.objective or "").strip()[:500] or None
    objective = requested_objective
    effective_max_steps = _bounded_kernel_max_steps(body.max_steps)
    resumed_from: AgentJob | None = None
    resume_checkpoint: dict[str, Any] | None = None
    if body.resume_from_job_id:
        resumed_from = await _owned_agent_job(db, user_id, body.resume_from_job_id)
        if resumed_from.agent != "kernel":
            raise HTTPException(status_code=409, detail="agent_job_not_resumable")
        if resumed_from.status in {"pending", "running", "cancelling"}:
            raise HTTPException(status_code=409, detail="agent_job_still_active")
        if resumed_from.status not in {"failed", "cancelled"}:
            raise HTTPException(status_code=409, detail="agent_job_not_resumable")
        source_objective = str((resumed_from.payload or {}).get("objective") or "").strip()[:500] or None
        if objective is None:
            objective = source_objective
        if (
            (requested_objective is None or requested_objective == source_objective)
            and _checkpoint_step_index(resumed_from.checkpoint) is not None
        ):
            resume_checkpoint = dict(resumed_from.checkpoint)
            # The cumulative counters belong to the conversation checkpoint,
            # while ``run_*`` counters belong to one durable job attempt. A
            # resumed job starts a fresh attempt, so inheriting those deltas
            # would double-count the source run if recovery happens before the
            # first new progress checkpoint is written.
            inherited_usage = checkpoint_usage(resume_checkpoint)
            resume_checkpoint["usage"] = {
                **inherited_usage,
                "run_model_calls": 0,
                "run_estimated_input_tokens": 0,
                "run_estimated_output_tokens": 0,
                "run_estimated_total_tokens": 0,
            }
            effective_max_steps = _bounded_kernel_max_steps(
                (resumed_from.payload or {}).get("max_steps"), body.max_steps
            )

    now = utc_now_db().replace(microsecond=0)
    job_id = new_job_id()
    job = AgentJob(
        id=job_id,
        user_id=user_id,
        agent="kernel",
        task="run",
        status="pending",
        scenario="agent_kernel_v1",
        run_key=f"kernel:{job_id}",
        attempt_count=(int(resumed_from.attempt_count or 0) + 1) if resumed_from else 1,
        scheduled_for=now,
        resumed_from_job_id=resumed_from.id if resumed_from else None,
        checkpoint=resume_checkpoint,
        payload={
            "objective": objective,
            "max_steps": effective_max_steps,
            "resume_mode": "checkpoint" if resume_checkpoint else "restart",
        },
        result={"status": "pending", "steps": []},
        summary=(
            f"AgentKernel 已从 step {_checkpoint_step_index(resume_checkpoint)} 准备续跑"
            if resume_checkpoint
            else "AgentKernel 已准备，等待开始"
        ),
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)
    return job


@router.post("/kernel/jobs")
async def prepare_kernel_job(
    body: AgentKernelRunRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Persist a cancellable job before the first model request starts."""

    job = await _prepare_kernel_job(db, int(current_user.id), body)
    return {"job": agent_manager._job_to_dict(job)}


@router.get("/weekly-report")
async def get_weekly_report(
    time_zone: str = Query("UTC", min_length=1, max_length=64),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return a read-only weekly learning review draft.

    It intentionally exposes no automatic write path: every recommended
    action still sends the learner to the existing confirmation-first flows.
    """
    try:
        return await build_weekly_learning_report(
            db,
            int(current_user.id),
            time_zone=time_zone,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=redact_sensitive_text(exc)) from exc


@router.post("/kernel/run")
async def run_kernel(
    body: AgentKernelRunRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """运行 AgentKernel 多步工具循环（决策 D4）。

    只读工具循环 + 终态行动建议；写入仍走既有草案确认流。
    未配置 AI Key 时返回 unavailable 状态而非 5xx（可靠性基线）。
    """
    user_id = int(current_user.id)
    now = utc_now_db().replace(microsecond=0)
    if body.prepared_job_id:
        if body.resume_from_job_id:
            raise HTTPException(status_code=400, detail="conflicting_kernel_job_ids")
        job = await _owned_agent_job(db, user_id, body.prepared_job_id)
        if job.agent != "kernel" or job.scenario != "agent_kernel_v1":
            raise HTTPException(status_code=409, detail="agent_job_not_runnable")
    else:
        job = await _prepare_kernel_job(db, user_id, body)

    job_id = str(job.id)
    if job.status != "pending":
        raise HTTPException(status_code=409, detail="agent_job_not_pending")
    run_owner = new_job_id()
    objective = str((job.payload or {}).get("objective") or "").strip()[:500] or None
    max_steps = _bounded_kernel_max_steps((job.payload or {}).get("max_steps"))
    try:
        await lock_agent_kernel_run_slot(db, user_id, current_job_id=job_id)
    except AgentKernelRunConflict as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail=redact_sensitive_text(exc)) from exc

    daily_budget = await get_agent_kernel_daily_budget(
        db,
        user_id,
        model_call_limit=settings.AGENT_KERNEL_DAILY_MODEL_CALLS_PER_USER,
        estimated_token_limit=settings.AGENT_KERNEL_DAILY_ESTIMATED_TOKENS_PER_USER,
        now=now,
    )
    inherited_usage = checkpoint_usage(job.checkpoint)
    remaining_daily_calls = int(daily_budget["remaining_model_calls"])
    remaining_daily_tokens = int(daily_budget["remaining_estimated_tokens"])
    if remaining_daily_calls <= 0 or remaining_daily_tokens <= 0:
        budget_reason = (
            "daily_model_call_limit"
            if remaining_daily_calls <= 0
            else "daily_estimated_token_limit"
        )
        usage = {
            **inherited_usage,
            "run_model_calls": 0,
            "run_estimated_input_tokens": 0,
            "run_estimated_output_tokens": 0,
            "run_estimated_total_tokens": 0,
            "model_call_limit": settings.AGENT_KERNEL_MAX_MODEL_CALLS,
            "estimated_token_limit": settings.AGENT_KERNEL_MAX_ESTIMATED_TOKENS,
            "budget_reason": budget_reason,
            "daily_budget": daily_budget,
        }
        fallback = await _build_kernel_rules_fallback(
            db,
            user_id,
            reason="daily_cost_budget_exceeded",
        )
        job.status = "failed"
        job.finished_at = now
        job.summary = "今日 AgentKernel 预算已用完，已提供规则简报"
        job.result = {
            "status": "fallback",
            "error": "daily_cost_budget_exceeded",
            "steps": [],
            "usage": usage,
            **fallback,
        }
        db.add(
            AgentExecutionLog(
                id=new_job_id(),
                user_id=user_id,
                job_id=job_id,
                agent="kernel",
                status="budget_exceeded",
                message="今日 AgentKernel 预算已用完；没有发起模型调用或执行写入",
                extra_metadata={
                    "budget_reason": budget_reason,
                    "daily_budget": daily_budget,
                    "fallback_available": bool(fallback["next_actions"]),
                },
                created_at=now,
            )
        )
        await db.commit()
        return {
            "status": "fallback",
            "strategy": fallback["strategy"],
            "fallback_plan": fallback["fallback_plan"],
            "next_actions": fallback["next_actions"],
            "steps": [],
            "error": "daily_cost_budget_exceeded",
            "usage": usage,
            "fallback": fallback["fallback"],
            "job_id": job_id,
        }

    effective_max_model_calls = min(
        settings.AGENT_KERNEL_MAX_MODEL_CALLS,
        inherited_usage["model_calls"] + remaining_daily_calls,
    )
    effective_max_estimated_tokens = min(
        settings.AGENT_KERNEL_MAX_ESTIMATED_TOKENS,
        inherited_usage["estimated_total_tokens"] + remaining_daily_tokens,
    )
    claim_payload = {
        **(job.payload or {}),
        "budget": {
            "daily_before": daily_budget,
            "effective_model_call_limit": effective_max_model_calls,
            "effective_estimated_token_limit": effective_max_estimated_tokens,
        },
    }
    lease_expires_at = now + timedelta(seconds=settings.AGENT_KERNEL_LEASE_SECONDS)
    claimed = await db.execute(
        update(AgentJob)
        .where(
            AgentJob.id == job_id,
            AgentJob.user_id == user_id,
            AgentJob.agent == "kernel",
            AgentJob.scenario == "agent_kernel_v1",
            AgentJob.status == "pending",
        )
        .values(
            status="running",
            started_at=now,
            payload=claim_payload,
            result={"status": "running", "steps": []},
            summary="AgentKernel 正在读取证据",
            lease_owner=run_owner,
            lease_expires_at=lease_expires_at,
            updated_at=now,
        )
        .execution_options(synchronize_session=False)
    )
    if claimed.rowcount != 1:
        await db.rollback()
        raise HTTPException(status_code=409, detail="agent_job_not_pending")
    await db.refresh(job)
    db.add(
        AgentExecutionLog(
            id=new_job_id(),
            user_id=user_id,
            job_id=job_id,
            agent="kernel",
            status="started",
            message="AgentKernel 已开始，只会调用只读工具",
            extra_metadata={
                "resumed_from_job_id": job.resumed_from_job_id,
                "resume_mode": (job.payload or {}).get("resume_mode"),
                "checkpoint_step": _checkpoint_step_index(job.checkpoint),
            },
            created_at=utc_now_db(),
        )
    )
    # The job must be visible to a concurrent cancellation request before the
    # first provider call starts.
    await db.commit()

    try:
        from app.ai.factory import AIProviderFactory

        provider = await AIProviderFactory.create_provider(
            db=db, scenario="agent_planner", user_id=user_id
        )
    except Exception:
        await db.refresh(
            job,
            attribute_names=["status", "cancel_requested_at", "lease_owner", "result"],
        )
        if job.lease_owner != run_owner:
            return _kernel_response_from_job(job)
        if job.cancel_requested_at or job.status in {"cancelling", "cancelled"}:
            job.status = "cancelled"
            job.finished_at = utc_now_db().replace(microsecond=0)
            job.lease_owner = None
            job.lease_expires_at = None
            job.summary = "AgentKernel 已取消"
            job.result = {
                "status": "cancelled",
                "reason": "cancelled_by_user",
                "steps": [],
            }
            db.add(
                AgentExecutionLog(
                    id=new_job_id(),
                    user_id=user_id,
                    job_id=job_id,
                    agent="kernel",
                    status="cancelled",
                    message="AgentKernel 已取消；没有执行任何写入",
                    created_at=utc_now_db(),
                )
            )
            await db.commit()
            return {
                "status": "cancelled",
                "reason": "cancelled_by_user",
                "strategy": None,
                "fallback_plan": None,
                "next_actions": [],
                "steps": [],
                "job_id": job_id,
            }
        fallback = await _build_kernel_rules_fallback(
            db,
            user_id,
            reason="ai_provider_unavailable",
        )
        job.status = "failed"
        job.finished_at = utc_now_db().replace(microsecond=0)
        job.lease_owner = None
        job.lease_expires_at = None
        job.summary = "AI Provider 当前不可用，已提供规则简报"
        job.result = {
            "status": "fallback",
            "reason": "ai_provider_unavailable",
            "error": "ai_provider_unavailable",
            "steps": [],
            **fallback,
        }
        db.add(
            AgentExecutionLog(
                id=new_job_id(),
                user_id=user_id,
                job_id=job_id,
                agent="kernel",
                status="fallback",
                message="AI Provider 当前不可用；已切换到规则简报，没有执行任何写入",
                extra_metadata={"fallback_available": bool(fallback["next_actions"])},
                created_at=utc_now_db(),
            )
        )
        await db.commit()
        return {
            "status": "fallback",
            "reason": "ai_provider_unavailable",
            "strategy": fallback["strategy"],
            "fallback_plan": fallback["fallback_plan"],
            "next_actions": fallback["next_actions"],
            "steps": [],
            "error": "ai_provider_unavailable",
            "fallback": fallback["fallback"],
            "job_id": job_id,
        }

    steps_payload: list[dict[str, Any]] = []
    lease_lost = False

    async def should_cancel() -> bool:
        nonlocal lease_lost
        await db.refresh(
            job,
            attribute_names=["status", "cancel_requested_at", "lease_owner", "lease_expires_at"],
        )
        if job.lease_owner != run_owner or job.status not in {"running", "cancelling"}:
            lease_lost = True
            return True
        if job.cancel_requested_at or job.status == "cancelling":
            return True
        job.lease_expires_at = utc_now_db().replace(microsecond=0) + timedelta(
            seconds=settings.AGENT_KERNEL_LEASE_SECONDS
        )
        job.updated_at = utc_now_db()
        await db.commit()
        return False

    async def persist_progress(step: Any, checkpoint: dict[str, Any] | None) -> None:
        payload = _kernel_step_payload(step)
        steps_payload.append(payload)
        await db.refresh(job, attribute_names=["status", "lease_owner", "cancel_requested_at"])
        if job.lease_owner != run_owner or job.status not in {"running", "cancelling"}:
            raise RuntimeError("agent_kernel_lease_lost")
        job.result = {
            "status": "running",
            "steps": list(steps_payload),
            "resumed_from_job_id": job.resumed_from_job_id,
            "usage": (
                checkpoint.get("usage")
                if isinstance(checkpoint, dict) and isinstance(checkpoint.get("usage"), dict)
                else {}
            ),
        }
        if checkpoint is not None:
            job.checkpoint = checkpoint
        job.lease_expires_at = utc_now_db().replace(microsecond=0) + timedelta(
            seconds=settings.AGENT_KERNEL_LEASE_SECONDS
        )
        job.updated_at = utc_now_db()
        db.add(
            AgentExecutionLog(
                id=new_job_id(),
                user_id=user_id,
                job_id=job_id,
                agent="kernel",
                status=step.kind,
                message=(
                    f"step{step.index} {step.kind}"
                    + (f" tool={step.tool}" if step.tool else "")
                    + (f" | {step.thought}" if step.thought else "")
                )[:500],
                extra_metadata={"step": payload},
                created_at=utc_now_db(),
            )
        )
        await db.commit()

    try:
        result = await run_agent_kernel(
            db,
            user_id,
            provider,
            objective=objective,
            max_steps=max_steps,
            max_model_calls=effective_max_model_calls,
            max_estimated_tokens=effective_max_estimated_tokens,
            should_cancel=should_cancel,
            resume_checkpoint=job.checkpoint if isinstance(job.checkpoint, dict) else None,
            on_progress=persist_progress,
        )
    except Exception:
        await db.rollback()
        job = await _owned_agent_job(db, user_id, job_id)
        if job.lease_owner != run_owner:
            return _kernel_response_from_job(job)
        job.status = "failed"
        job.finished_at = utc_now_db().replace(microsecond=0)
        job.lease_owner = None
        job.lease_expires_at = None
        job.summary = "AgentKernel 运行失败"
        job.result = {
            "status": "failed",
            "error": "kernel_execution_failed",
            "steps": steps_payload,
        }
        db.add(
            AgentExecutionLog(
                id=new_job_id(),
                user_id=user_id,
                job_id=job_id,
                agent="kernel",
                status="failed",
                message="AgentKernel 运行失败；没有执行任何写入",
                created_at=utc_now_db(),
            )
        )
        await db.commit()
        return {
            "status": "failed",
            "strategy": None,
            "fallback_plan": None,
            "next_actions": [],
            "steps": steps_payload,
            "error": "kernel_execution_failed",
            "job_id": job_id,
        }

    await db.refresh(job, attribute_names=["status", "lease_owner", "result"])
    if lease_lost or job.lease_owner != run_owner:
        return _kernel_response_from_job(job)
    rules_fallback: dict[str, Any] | None = None
    effective_status = result.status
    effective_strategy = result.strategy
    effective_fallback_plan = result.fallback_plan
    effective_actions = result.next_actions
    if result.status not in {"completed", "cancelled"}:
        rules_fallback = await _build_kernel_rules_fallback(
            db,
            user_id,
            reason=result.error or result.status,
        )
        if rules_fallback["next_actions"]:
            effective_status = "fallback"
            effective_strategy = rules_fallback["strategy"]
            effective_fallback_plan = rules_fallback["fallback_plan"]
            effective_actions = rules_fallback["next_actions"]
    job.status = result.status if result.status in {"completed", "cancelled"} else "failed"
    job.finished_at = utc_now_db().replace(microsecond=0)
    job.lease_owner = None
    job.lease_expires_at = None
    job.summary = effective_strategy or result.error or result.status
    result_usage = dict(result.usage)
    result_usage["daily_budget"] = daily_budget_after_run(daily_budget, result_usage)
    job.result = {
        "status": effective_status,
        "strategy": effective_strategy,
        "fallback_plan": effective_fallback_plan,
        "next_actions": effective_actions,
        "steps": steps_payload,
        "error": result.error,
        "usage": result_usage,
    }
    if rules_fallback is not None:
        job.result["fallback"] = rules_fallback["fallback"]
        if rules_fallback["next_actions"]:
            db.add(
                AgentExecutionLog(
                    id=new_job_id(),
                    user_id=user_id,
                    job_id=job_id,
                    agent="kernel",
                    status="fallback",
                    message="AgentKernel 未完成，已切换到规则简报；没有执行任何写入",
                    extra_metadata={
                        "reason": result.error or result.status,
                        "fallback_action_count": len(rules_fallback["next_actions"]),
                    },
                    created_at=utc_now_db(),
                )
            )
    await db.commit()

    return {
        "status": effective_status,
        "strategy": effective_strategy,
        "fallback_plan": effective_fallback_plan,
        "next_actions": effective_actions,
        "steps": steps_payload,
        "error": result.error,
        "usage": result_usage,
        "fallback": rules_fallback["fallback"] if rules_fallback is not None else None,
        "job_id": job_id,
    }


@router.get("/jobs/{job_id}")
async def get_agent_job_replay(
    job_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return one user-owned Agent run and its ordered, sanitized replay."""

    user_id = int(current_user.id)
    job = await _owned_agent_job(db, user_id, job_id)
    logs_result = await db.execute(
        select(AgentExecutionLog)
        .where(
            AgentExecutionLog.user_id == user_id,
            AgentExecutionLog.job_id == job_id,
        )
        .order_by(AgentExecutionLog.created_at, AgentExecutionLog.id)
    )
    return {
        "job": agent_manager._job_to_dict(job),
        "logs": [agent_manager._log_to_dict(log) for log in logs_result.scalars().all()],
    }


@router.post("/jobs/{job_id}/actions/{action_id}/draft")
async def draft_kernel_job_action(
    job_id: str,
    action_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Build and persist a user-owned confirmation receipt without domain writes."""

    try:
        payload = await prepare_kernel_action_confirmation(
            db,
            int(current_user.id),
            job_id,
            action_id,
        )
        await db.commit()
        return payload
    except KernelActionNotFound as exc:
        raise HTTPException(status_code=404, detail=redact_sensitive_text(exc)) from exc
    except KernelActionConflict as exc:
        raise HTTPException(status_code=409, detail=redact_sensitive_text(exc)) from exc


@router.post("/jobs/{job_id}/actions/{action_id}/confirm")
async def confirm_kernel_job_action(
    job_id: str,
    action_id: str,
    body: AgentKernelActionConfirmRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Execute one persisted Kernel draft exactly once after explicit confirmation."""

    try:
        user_id = int(current_user.id)
        result = await execute_kernel_action_confirmation(
            db,
            user_id,
            job_id,
            action_id,
            body.draft_id,
        )
        if not result.get("idempotent"):
            created_task = result.get("created_task") or {}
            if result.get("status") == "created" and created_task.get("id"):
                await record_learning_event(
                    db,
                    user_id,
                    "task.created",
                    source="agent_kernel_confirm",
                    payload={
                        "title": created_task.get("title"),
                        "job_id": job_id,
                        "action_id": action_id,
                        "draft_id": body.draft_id,
                    },
                    goal_id=int(created_task["goal_id"]) if created_task.get("goal_id") else None,
                    task_id=int(created_task["id"]),
                    dedupe_key=f"kernel:{body.draft_id}:task.created",
                )
            await record_learning_event(
                db,
                user_id,
                "agent.action_feedback",
                source="agent_kernel_confirm",
                payload={
                    "job_id": job_id,
                    "action_id": action_id,
                    "draft_id": body.draft_id,
                    "outcome": result.get("status"),
                    "route": result.get("route"),
                },
                goal_id=int(created_task["goal_id"]) if created_task.get("goal_id") else None,
                task_id=int(created_task["id"]) if created_task.get("id") else None,
                dedupe_key=f"kernel:{body.draft_id}:feedback",
            )
        await db.commit()
        return result
    except KernelActionNotFound as exc:
        raise HTTPException(status_code=404, detail=redact_sensitive_text(exc)) from exc
    except KernelActionConflict as exc:
        raise HTTPException(status_code=409, detail=redact_sensitive_text(exc)) from exc


def _agent_job_sse_event(event: str, payload: dict[str, Any]) -> str:
    return (
        f"event: {event}\n"
        f"data: {json.dumps(payload, ensure_ascii=False, separators=(',', ':'), default=str)}\n\n"
    )


async def _agent_job_event_stream(user_id: int, job_id: str):
    """Replay persisted logs, then follow the job until its terminal state."""

    seen_log_ids: set[str] = set()
    started_at = monotonic()
    last_emitted_at = started_at
    snapshot_sent = False

    while True:
        async with async_session_maker() as session:
            job = await session.scalar(
                select(AgentJob).where(AgentJob.id == job_id, AgentJob.user_id == user_id)
            )
            if job is None:
                yield _agent_job_sse_event("error", {"type": "error", "code": "agent_job_not_found"})
                return
            logs_result = await session.execute(
                select(AgentExecutionLog)
                .where(
                    AgentExecutionLog.user_id == user_id,
                    AgentExecutionLog.job_id == job_id,
                )
                .order_by(AgentExecutionLog.created_at, AgentExecutionLog.id)
            )
            job_payload = agent_manager._job_to_dict(job)
            logs = [agent_manager._log_to_dict(log) for log in logs_result.scalars().all()]

        if not snapshot_sent:
            yield _agent_job_sse_event("snapshot", {"type": "snapshot", "job": job_payload})
            snapshot_sent = True
            last_emitted_at = monotonic()

        for log in logs:
            log_id = str(log.get("id") or "")
            if not log_id or log_id in seen_log_ids:
                continue
            seen_log_ids.add(log_id)
            yield _agent_job_sse_event("log", {"type": "log", "log": log})
            last_emitted_at = monotonic()

        if str(job_payload.get("status") or "") in AGENT_JOB_TERMINAL_STATUSES:
            yield _agent_job_sse_event("terminal", {"type": "terminal", "job": job_payload})
            return

        now = monotonic()
        if now - started_at >= AGENT_JOB_EVENT_MAX_SECONDS:
            yield _agent_job_sse_event(
                "timeout",
                {"type": "timeout", "job_id": job_id, "message": "stream_window_elapsed"},
            )
            return
        if now - last_emitted_at >= AGENT_JOB_EVENT_HEARTBEAT_SECONDS:
            yield ": keep-alive\n\n"
            last_emitted_at = now
        await asyncio.sleep(AGENT_JOB_EVENT_POLL_SECONDS)


@router.get("/jobs/{job_id}/events")
async def stream_agent_job_events(
    job_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Stream one owned Kernel job from durable logs; reconnects replay history."""

    user_id = int(current_user.id)
    job = await _owned_agent_job(db, user_id, job_id)
    if job.agent != "kernel" or job.scenario != "agent_kernel_v1":
        raise HTTPException(status_code=409, detail="agent_job_not_streamable")
    # The stream polls with short-lived sessions, so release the request
    # transaction before the response starts and never hold a DB connection
    # during model calls or client idle time.
    await db.rollback()
    return StreamingResponse(
        _agent_job_event_stream(user_id, job_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/jobs/{job_id}/cancel")
async def cancel_agent_job(
    job_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Request cooperative cancellation without touching another user's run."""

    user_id = int(current_user.id)
    job = await _owned_agent_job(db, user_id, job_id)
    if job.agent != "kernel" or job.scenario != "agent_kernel_v1":
        raise HTTPException(status_code=409, detail="agent_job_not_cancellable")
    if job.status in {"completed", "failed", "cancelled", "skipped"}:
        return {"job": agent_manager._job_to_dict(job), "changed": False}
    if job.cancel_requested_at or job.status == "cancelling":
        return {"job": agent_manager._job_to_dict(job), "changed": False}
    now = utc_now_db().replace(microsecond=0)
    job.cancel_requested_at = now
    if job.status == "pending":
        job.status = "cancelled"
        job.finished_at = now
        log_status = "cancelled"
        log_message = "用户在模型调用前取消；没有执行任何步骤或写入"
    else:
        job.status = "cancelling"
        log_status = "cancelling"
        log_message = "用户请求取消；运行会在当前只读步骤结束后停止"
    db.add(
        AgentExecutionLog(
            id=new_job_id(),
            user_id=user_id,
            job_id=job.id,
            agent=job.agent,
            status=log_status,
            message=log_message,
            created_at=utc_now_db(),
        )
    )
    await db.commit()
    await db.refresh(job)
    return {"job": agent_manager._job_to_dict(job), "changed": True}


@router.post("/tasks/trigger")
async def trigger_agent_task(
    body: AgentTaskTriggerRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """触发一个轻量 Agent 任务。"""
    try:
        return await agent_manager.trigger(
            db=db,
            user_id=int(current_user.id),
            agent_name=body.agent,
            task=body.task or "run",
            payload=body.payload or {},
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=redact_sensitive_text(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail="agent_execution_failed") from exc


@router.post("/tools/chat")
async def call_chat_agent_tool(
    body: AgentToolCallRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """调用 ChatAgent 的只读查询工具。"""
    return await agent_manager.call_chat_tool(
        db=db,
        user_id=int(current_user.id),
        tool=body.tool,
        query=body.query or "",
        limit=body.limit or 5,
    )


@router.get("/brief", response_model=AgentBriefResponse)
async def get_agent_brief(
    use_llm: bool = Query(False, description="是否尝试使用 LLM Planner 增强行动规划，失败会回退规则引擎"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取 Agent 今日简报：感知当前状态并给出下一步行动建议。"""
    return await build_agent_brief(db, int(current_user.id), use_llm=use_llm)


@router.get("/goal-context")
async def get_agent_goal_context(
    goal_id: int | None = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取以当前目标为中心的 Agent cockpit 上下文。"""
    return await build_goal_context(db, int(current_user.id), goal_id=goal_id)


@router.post("/write/draft")
async def draft_agent_write(
    body: AgentWriteDraftRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """根据自然语言生成写入草案；只预览，不直接写入。"""
    if not body.message.strip():
        raise HTTPException(status_code=400, detail="消息不能为空")
    return await build_agent_write_draft(db, int(current_user.id), body.message)


@router.post("/write/execute")
async def execute_agent_write(
    body: AgentWriteExecuteRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """确认执行自然语言写入草案。"""
    try:
        result = await execute_agent_write_draft(db, int(current_user.id), body.intent, body.draft)
        created = result.get("created") or {}
        if body.intent == "create_note" and (created.get("note") or {}).get("id"):
            note = created["note"]
            await record_learning_event(
                db,
                int(current_user.id),
                "note.created",
                source="agent_write",
                payload={"title": note.get("title"), "intent": body.intent},
                note_id=int(note["id"]),
                dedupe_key=f"agent:note.created:{note['id']}",
            )
        elif body.intent == "create_goal_tasks" and (created.get("goal") or {}).get("id"):
            goal = created["goal"]
            await record_learning_event(
                db,
                int(current_user.id),
                "goal.created" if not body.draft.get("existing_goal_id") else "goal.updated",
                source="agent_write",
                payload={"title": goal.get("title"), "task_count": len(created.get("tasks") or [])},
                goal_id=int(goal["id"]),
                dedupe_key=f"agent:goal_tasks:{goal['id']}:{len(created.get('tasks') or [])}",
            )
            for task in created.get("tasks") or []:
                if task.get("id"):
                    await record_learning_event(
                        db,
                        int(current_user.id),
                        "task.created",
                        source="agent_write",
                        payload={"title": task.get("title"), "planned_date": task.get("planned_date")},
                        goal_id=int(goal["id"]),
                        task_id=int(task["id"]),
                        dedupe_key=f"agent:task.created:{task['id']}",
                    )
        elif body.intent == "add_daily_plan_items" and (created.get("plan") or {}).get("id"):
            plan = created["plan"]
            await record_learning_event(
                db,
                int(current_user.id),
                "daily_plan.updated",
                source="agent_write",
                payload={"date": plan.get("date"), "item_count": len(created.get("items") or [])},
                dedupe_key=f"agent:daily_plan.updated:{plan['id']}:{len(created.get('items') or [])}",
            )
        await db.commit()
        return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=redact_sensitive_text(exc)) from exc


@router.get("/prompt")
async def get_agent_prompt_fragment(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """调试用：查看会注入聊天 system prompt 的 Agent 简报片段。"""
    brief = await build_agent_brief(db, int(current_user.id))
    return {"prompt": build_agent_prompt_snippet(brief)}


@router.get("/actions/{action_id}/draft", response_model=AgentActionDraftResponse)
async def get_agent_action_draft(
    action_id: str,
    use_llm: bool = Query(False, description="是否按 LLM Planner 生成的行动查找草案"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """把某个 Agent 行动转成可确认的执行草案；默认只预览，不写入数据。"""
    try:
        return await build_agent_action_draft(db, int(current_user.id), action_id, use_llm=use_llm)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=redact_sensitive_text(exc)) from exc


@router.post("/goal-context/actions/{action_id}/draft")
async def draft_agent_goal_context_action(
    action_id: str,
    body: AgentGoalActionDraftRequest | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Goal cockpit 的行动草案入口；复用现有 Agent 草稿契约。"""
    if body and body.message and body.message.strip():
        return await build_agent_write_draft(db, int(current_user.id), body.message)
    try:
        return await build_agent_action_draft(db, int(current_user.id), action_id, use_llm=False)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=redact_sensitive_text(exc)) from exc


@router.post("/goal-context/actions/{action_id}/feedback")
async def record_agent_goal_context_action_feedback(
    action_id: str,
    body: AgentFeedbackRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """记录用户对目标 cockpit 行动的反馈。"""
    effectiveness = body.effectiveness
    if effectiveness is not None:
        effectiveness = max(0.0, min(1.0, float(effectiveness)))
    action = None
    try:
        context = await build_goal_context(db, int(current_user.id))
        focus = context.get("today_focus") or {}
        if focus.get("action_id") == action_id or focus.get("id") == action_id:
            action = {
                "id": action_id,
                "title": focus.get("title"),
                "reason": focus.get("reason"),
                "action_type": "goal_context",
                "route": focus.get("route"),
                "target": focus.get("target"),
                "source": "goal_context",
            }
    except Exception:
        action = None
    result = await remember_agent_feedback(
        db,
        int(current_user.id),
        action_id,
        body.outcome,
        body.notes,
        effectiveness,
        action,
        body.reason_code,
    )
    await record_learning_event(
        db,
        int(current_user.id),
        "agent.action_feedback",
        source="agent_goal_context",
        payload={"action_id": action_id, "outcome": body.outcome, "reason_code": body.reason_code},
        dedupe_key=f"agent.goal_context.feedback:{action_id}:{body.outcome}:{body.reason_code or ''}",
    )
    await db.commit()
    return result


@router.post("/actions/{action_id}/execute", response_model=AgentActionExecuteResponse)
async def execute_agent_action_endpoint(
    action_id: str,
    use_llm: bool = Query(False, description="是否按 LLM Planner 生成的行动执行"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """确认执行一个 Agent 行动。当前只自动创建低风险任务，其余行动记录反馈后跳转。"""
    try:
        user_id = int(current_user.id)
        result = await execute_agent_action(db, user_id, action_id, use_llm=use_llm)
        action = result.get("action") or {}
        created_task = result.get("created_task") or {}
        if created_task.get("id"):
            await record_learning_event(
                db,
                user_id,
                "task.created",
                source="agent_action_execute",
                payload={
                    "title": created_task.get("title"),
                    "action_id": action_id,
                    "action_type": action.get("action_type"),
                    "planned_date": created_task.get("planned_date"),
                },
                goal_id=int(created_task["goal_id"]) if created_task.get("goal_id") else None,
                task_id=int(created_task["id"]),
                dedupe_key=f"agent:action:{action_id}:task.created:{created_task['id']}",
            )
        await record_learning_event(
            db,
            user_id,
            "agent.action_feedback",
            source="agent_action_execute",
            payload={
                "action_id": action_id,
                "action_type": action.get("action_type"),
                "outcome": "accepted" if result.get("status") == "created" else result.get("status"),
                "route": result.get("route"),
            },
            goal_id=int(created_task["goal_id"]) if created_task.get("goal_id") else None,
            task_id=int(created_task["id"]) if created_task.get("id") else None,
            dedupe_key=f"agent:action:{action_id}:feedback:{result.get('status')}",
        )
        await db.commit()
        return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=redact_sensitive_text(exc)) from exc


@router.post("/actions/{action_id}/feedback")
async def record_agent_action_feedback(
    action_id: str,
    body: AgentFeedbackRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """记录用户对 Agent 行动的反馈，写入 episodic memory 供后续规划参考。"""
    effectiveness = body.effectiveness
    if effectiveness is not None:
        effectiveness = max(0.0, min(1.0, float(effectiveness)))
    action = None
    try:
        brief = await build_agent_brief(db, int(current_user.id), use_llm=False)
        action = next((item for item in brief.get("next_actions", []) if item.get("id") == action_id), None)
    except Exception:
        action = None
    result = await remember_agent_feedback(
        db,
        int(current_user.id),
        action_id,
        body.outcome,
        body.notes,
        effectiveness,
        action,
        body.reason_code,
    )
    await record_learning_event(
        db,
        int(current_user.id),
        "agent.action_feedback",
        source="agent_actions",
        payload={"action_id": action_id, "outcome": body.outcome, "reason_code": body.reason_code},
        dedupe_key=f"agent.actions.feedback:{action_id}:{body.outcome}:{body.reason_code or ''}",
    )
    await db.commit()
    return result



@router.patch("/profile/items/{item_id}")
async def control_agent_profile_item(
    item_id: str,
    body: AgentProfileControlRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """控制 Agent 学到的画像条目：忽略、标记不准确、锁定或恢复。"""
    try:
        return await update_agent_profile_item(db, int(current_user.id), item_id, body.operation)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=redact_sensitive_text(exc)) from exc
