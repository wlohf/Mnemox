"""Per-user AgentKernel budget accounting backed by durable job results."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import AgentJob
from app.models.user import User
from app.utils.utc import to_db_utc, utc_now_db


class AgentKernelRunConflict(ValueError):
    """Raised when one learner already has an active Kernel run."""


def _non_negative_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def checkpoint_usage(checkpoint: Any) -> dict[str, int]:
    raw = checkpoint.get("usage") if isinstance(checkpoint, dict) else None
    if not isinstance(raw, dict):
        raw = {}
    return {
        "model_calls": _non_negative_int(raw.get("model_calls")),
        "estimated_input_tokens": _non_negative_int(raw.get("estimated_input_tokens")),
        "estimated_output_tokens": _non_negative_int(raw.get("estimated_output_tokens")),
        "estimated_total_tokens": _non_negative_int(raw.get("estimated_total_tokens")),
    }


def _job_run_usage(result: Any) -> tuple[int, int]:
    usage = result.get("usage") if isinstance(result, dict) else None
    if not isinstance(usage, dict):
        return 0, 0
    # ``run_*`` avoids double-counting inherited checkpoint usage after a
    # resume. Fall back to the cumulative fields for results written before
    # per-attempt accounting existed.
    calls_key = "run_model_calls" if "run_model_calls" in usage else "model_calls"
    tokens_key = (
        "run_estimated_total_tokens"
        if "run_estimated_total_tokens" in usage
        else "estimated_total_tokens"
    )
    return _non_negative_int(usage.get(calls_key)), _non_negative_int(usage.get(tokens_key))


def _job_reconciled_usage(result: Any) -> tuple[int, int, float]:
    usage = result.get("usage") if isinstance(result, dict) else None
    if not isinstance(usage, dict):
        return 0, 0, 0.0
    actual_calls_key = "run_actual_usage_calls" if "run_actual_usage_calls" in usage else "actual_usage_calls"
    actual_tokens_key = "run_actual_total_tokens" if "run_actual_total_tokens" in usage else "actual_total_tokens"
    cost_key = "run_configured_cost_usd" if "run_configured_cost_usd" in usage else "configured_cost_usd"
    try:
        configured_cost = max(0.0, float(usage.get(cost_key) or 0.0))
    except (TypeError, ValueError):
        configured_cost = 0.0
    return (
        _non_negative_int(usage.get(actual_calls_key)),
        _non_negative_int(usage.get(actual_tokens_key)),
        configured_cost,
    )


async def lock_agent_kernel_run_slot(
    db: AsyncSession,
    user_id: int,
    *,
    current_job_id: str,
) -> None:
    """Serialize Kernel starts for one user and reject overlapping runs.

    PostgreSQL holds the user-row lock until the caller commits the job claim.
    This closes the check/claim race without keeping a transaction open during
    the model call. SQLite ignores ``FOR UPDATE`` but still follows the same
    product rule in local single-process mode.
    """

    owner_id = await db.scalar(select(User.id).where(User.id == user_id).with_for_update())
    if owner_id is None:
        raise AgentKernelRunConflict("agent_kernel_user_not_found")
    active_job_id = await db.scalar(
        select(AgentJob.id)
        .where(
            AgentJob.user_id == user_id,
            AgentJob.agent == "kernel",
            AgentJob.scenario == "agent_kernel_v1",
            AgentJob.status.in_(("running", "cancelling")),
            AgentJob.id != current_job_id,
        )
        .order_by(AgentJob.started_at, AgentJob.id)
        .limit(1)
    )
    if active_job_id is not None:
        raise AgentKernelRunConflict("agent_kernel_run_already_active")


async def get_agent_kernel_daily_budget(
    db: AsyncSession,
    user_id: int,
    *,
    model_call_limit: int,
    estimated_token_limit: int,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Aggregate this user's UTC-day consumption from terminal Kernel jobs."""

    observed_at = to_db_utc(now) if now is not None else utc_now_db()
    day_start = observed_at.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + timedelta(days=1)
    # Prepared jobs can cross midnight. Attribute consumption to the actual
    # run start, while retaining ``created_at`` as a compatibility fallback
    # for terminal jobs written before ``started_at`` was populated.
    consumed_at = func.coalesce(AgentJob.started_at, AgentJob.created_at)
    result = await db.execute(
        select(AgentJob.result).where(
            AgentJob.user_id == user_id,
            AgentJob.agent == "kernel",
            AgentJob.scenario == "agent_kernel_v1",
            AgentJob.status.in_(("completed", "failed", "cancelled")),
            consumed_at >= day_start,
            consumed_at < day_end,
        )
    )
    model_calls = 0
    estimated_tokens = 0
    actual_usage_calls = 0
    actual_tokens = 0
    configured_cost_usd = 0.0
    for stored_result in result.scalars().all():
        run_calls, run_tokens = _job_run_usage(stored_result)
        run_actual_calls, run_actual_tokens, run_configured_cost = _job_reconciled_usage(stored_result)
        model_calls += run_calls
        estimated_tokens += run_tokens
        actual_usage_calls += run_actual_calls
        actual_tokens += run_actual_tokens
        configured_cost_usd += run_configured_cost

    call_limit = max(1, int(model_call_limit))
    token_limit = max(512, int(estimated_token_limit))
    return {
        "date": day_start.date().isoformat(),
        "timezone": "UTC",
        "model_calls": model_calls,
        "estimated_tokens": estimated_tokens,
        "actual_usage_calls": actual_usage_calls,
        "actual_tokens": actual_tokens,
        "configured_cost_usd": round(configured_cost_usd, 8),
        "model_call_limit": call_limit,
        "estimated_token_limit": token_limit,
        "remaining_model_calls": max(0, call_limit - model_calls),
        "remaining_estimated_tokens": max(0, token_limit - estimated_tokens),
    }


def daily_budget_after_run(
    before: dict[str, Any],
    run_usage: dict[str, Any],
) -> dict[str, Any]:
    model_calls = _non_negative_int(before.get("model_calls")) + _non_negative_int(
        run_usage.get("run_model_calls")
    )
    estimated_tokens = _non_negative_int(before.get("estimated_tokens")) + _non_negative_int(
        run_usage.get("run_estimated_total_tokens")
    )
    actual_usage_calls = _non_negative_int(before.get("actual_usage_calls")) + _non_negative_int(
        run_usage.get("run_actual_usage_calls")
    )
    actual_tokens = _non_negative_int(before.get("actual_tokens")) + _non_negative_int(
        run_usage.get("run_actual_total_tokens")
    )
    try:
        configured_cost_usd = max(0.0, float(before.get("configured_cost_usd") or 0.0)) + max(
            0.0,
            float(run_usage.get("run_configured_cost_usd") or 0.0),
        )
    except (TypeError, ValueError):
        configured_cost_usd = max(0.0, float(before.get("configured_cost_usd") or 0.0))
    call_limit = _non_negative_int(before.get("model_call_limit"))
    token_limit = _non_negative_int(before.get("estimated_token_limit"))
    return {
        **before,
        "model_calls": model_calls,
        "estimated_tokens": estimated_tokens,
        "actual_usage_calls": actual_usage_calls,
        "actual_tokens": actual_tokens,
        "configured_cost_usd": round(configured_cost_usd, 8),
        "remaining_model_calls": max(0, call_limit - model_calls),
        "remaining_estimated_tokens": max(0, token_limit - estimated_tokens),
    }
