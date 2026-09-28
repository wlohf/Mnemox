"""Transactional, conservative accounting for individual extraction LLM calls.

The caller owns the surrounding transaction.  These helpers deliberately never
commit or roll back so a call reservation is atomic with the run lifecycle work
that caused it.
"""
from __future__ import annotations

import math
from datetime import datetime
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.extraction_budget import ExtractionCall, ExtractionDailyBudget
from app.models.knowledge import KnowledgeExtractionRun, KnowledgeUnit
from app.utils.dialect import SUPPORTED_DIALECTS, conflict_insert, dialect_name
from app.utils.utc import to_db_utc, utc_now_db


class ExtractionBudgetExceeded(ValueError):
    """Raised before issuing a call whose durable budget cannot accommodate it."""


class ExtractionLeaseLost(RuntimeError):
    """Raised when a reservation is attempted with a stale extraction-run lease."""


_SETTLED_STATES = frozenset({"succeeded", "failed", "unknown"})


def _require_supported_database(db: AsyncSession) -> None:
    # Fail before any reservation side effect rather than midway through one.
    if dialect_name(db) not in SUPPORTED_DIALECTS:
        raise RuntimeError("Extraction budget accounting requires SQLite or PostgreSQL.")


def _positive_int(value: Any, *, name: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a positive integer")
    try:
        normalized = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a positive integer") from exc
    if normalized <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return normalized


def _observed_at(now: datetime | None) -> datetime:
    return to_db_utc(now) if now is not None else utc_now_db()


def _normalized_optional(value: str | None, *, limit: int) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    if not normalized:
        return None
    if len(normalized) > limit:
        raise ValueError("provider/model metadata is too long")
    return normalized


def _sanitize_usage(value: Any) -> dict[str, Any]:
    """Only the provider-neutral numeric contract is retained; never arbitrary keys."""
    if not isinstance(value, dict):
        return {}
    result = {}
    for key in ('input_tokens', 'output_tokens', 'total_tokens', 'configured_cost_usd'):
        raw = value.get(key)
        if isinstance(raw, (int, float)) and not isinstance(raw, bool) and math.isfinite(raw):
            result[key] = max(0, raw)
    return result


def _reported_total_tokens(usage: dict[str, Any]) -> int:
    return max(
        int(usage.get('total_tokens', 0)),
        int(usage.get('input_tokens', 0)) + int(usage.get('output_tokens', 0)),
    )


async def _ensure_daily_bucket(
    db: AsyncSession,
    *,
    user_id: int,
    execution_day,
) -> None:
    values = {"user_id": user_id, "execution_day": execution_day, "charged_tokens": 0}
    await db.execute(
        conflict_insert(db, ExtractionDailyBudget)
        .values(**values)
        .on_conflict_do_nothing(index_elements=["user_id", "execution_day"])
    )


async def _refresh_run_usage(db: AsyncSession, run_id: int) -> None:
    """Derived billing metadata may advance after cancellation, never run status."""
    calls = list((await db.scalars(select(ExtractionCall).where(ExtractionCall.run_id == run_id))).all())
    usage = {
        'call_count': len(calls),
        'estimated_tokens': sum(call.estimated_tokens for call in calls),
        'charged_tokens': sum(call.charged_tokens for call in calls),
        'unknown_calls': sum(call.state in ('reserved', 'unknown') for call in calls),
    }
    for key in ('input_tokens', 'output_tokens', 'total_tokens', 'configured_cost_usd'):
        values = [(call.usage or {})[key] for call in calls if key in (call.usage or {})]
        if values:
            usage[key] = sum(values)
    await db.execute(update(KnowledgeExtractionRun).where(KnowledgeExtractionRun.id == run_id)
                     .values(usage=usage).execution_options(synchronize_session=False))


async def reserve_extraction_call(
    db: AsyncSession,
    *,
    call_id: str,
    user_id: int,
    run_id: int,
    unit_id: int | None,
    lease_token: str,
    estimated_tokens: int,
    provider: str | None = None,
    model: str | None = None,
    now: datetime | None = None,
) -> ExtractionCall:
    """Durably reserve budget for one provider attempt without committing it.

    The run no-op update is intentional: SQLite ignores ``FOR UPDATE``, while a
    DML write lock serializes concurrent local sessions before run aggregates are
    inspected.  PostgreSQL additionally gets a real row lock from the select.
    """

    _require_supported_database(db)
    normalized_call_id = str(call_id).strip()
    normalized_lease = str(lease_token).strip()
    if not normalized_call_id or len(normalized_call_id) > 36:
        raise ValueError("call_id must be a non-empty UUID-sized string")
    if not normalized_lease or len(normalized_lease) > 36:
        raise ExtractionLeaseLost("extraction lease token is invalid")
    estimate = _positive_int(estimated_tokens, name="estimated_tokens")
    owner_id = int(user_id)
    extraction_run_id = int(run_id)
    extraction_unit_id = int(unit_id) if unit_id is not None else None
    normalized_provider = _normalized_optional(provider, limit=80)
    normalized_model = _normalized_optional(model, limit=120)

    # Lock order is always Run -> Day.  The UPDATE is a real lock even on SQLite.
    locked = await db.scalar(
        update(KnowledgeExtractionRun)
        .where(KnowledgeExtractionRun.id == extraction_run_id,
               KnowledgeExtractionRun.user_id == owner_id,
               KnowledgeExtractionRun.status == 'running',
               KnowledgeExtractionRun.lease_token == normalized_lease,
               KnowledgeExtractionRun.lease_expires_at > _observed_at(now))
        .values(updated_at=KnowledgeExtractionRun.updated_at)
        .returning(KnowledgeExtractionRun.id).execution_options(synchronize_session=False)
    )
    if locked is None:
        raise ExtractionLeaseLost('Extraction lease is missing, stale, or no longer owned')
    observed = _observed_at(now)
    execution_day = observed.date()
    run = await db.scalar(
        select(KnowledgeExtractionRun)
        .where(KnowledgeExtractionRun.id == extraction_run_id)
        .with_for_update().execution_options(populate_existing=True)
    )
    if (
        run is None
        or int(run.user_id) != owner_id
        or run.status != "running"
        or str(run.lease_token or "") != normalized_lease
        or run.lease_expires_at is None
        or run.lease_expires_at <= observed
    ):
        raise ExtractionLeaseLost("extraction run lease is missing, stale, or no longer owned")

    if extraction_unit_id is not None:
        owned_unit = await db.scalar(select(KnowledgeUnit.id).where(
            KnowledgeUnit.id == extraction_unit_id, KnowledgeUnit.user_id == owner_id,
            KnowledgeUnit.source_revision_id == run.source_revision_id,
        ))
        if owned_unit is None:
            raise ExtractionLeaseLost('Extraction unit does not belong to the leased source revision')

    existing = await db.scalar(select(ExtractionCall).where(ExtractionCall.id == normalized_call_id))
    if existing is not None:
        same_identity = (
            int(existing.user_id) == owner_id
            and int(existing.run_id) == extraction_run_id
            and existing.unit_id == extraction_unit_id
            and existing.lease_token == normalized_lease
            and existing.execution_day == execution_day
            and int(existing.estimated_tokens) == estimate
            and existing.provider == normalized_provider
            and existing.model == normalized_model
        )
        if not same_identity:
            raise ValueError("call_id was already reserved for different extraction call identity")
        return existing

    call_limit = int(settings.KNOWLEDGE_LLM_MAX_CALLS_PER_RUN)
    run_token_limit = int(settings.KNOWLEDGE_LLM_MAX_ESTIMATED_TOKENS_PER_RUN)
    run_count, run_charged = (
        await db.execute(
            select(
                func.count(ExtractionCall.id),
                func.coalesce(func.sum(ExtractionCall.charged_tokens), 0),
            ).where(ExtractionCall.run_id == extraction_run_id)
        )
    ).one()
    review_required = await db.scalar(select(KnowledgeExtractionRun.id).where(
        KnowledgeExtractionRun.user_id == owner_id, KnowledgeExtractionRun.budget_review_required.is_(True),
    ).limit(1))
    legacy_usage = (await db.scalars(select(KnowledgeExtractionRun.usage).where(
        KnowledgeExtractionRun.user_id == owner_id,
        KnowledgeExtractionRun.extractor_type == 'llm',
        ~select(ExtractionCall.id).where(ExtractionCall.run_id == KnowledgeExtractionRun.id).exists(),
    ))).all()
    if review_required is not None or any(
        any((usage or {}).get(key) for key in ('call_count', 'estimated_tokens', 'total_tokens'))
        for usage in legacy_usage
    ):
        raise ExtractionBudgetExceeded('Legacy extraction accounting requires operator review; all LLM runs for this user are paused')
    if int(run_count) + 1 > call_limit or int(run_charged) + estimate > run_token_limit:
        raise ExtractionBudgetExceeded("extraction run call or token budget exceeded")

    # The upsert acquires/creates the user/day serialization row.  The conditional
    # UPDATE makes the preflight cap atomic across runs and worker processes.
    await _ensure_daily_bucket(
        db,
        user_id=owner_id,
        execution_day=execution_day,
    )
    daily_limit = int(settings.KNOWLEDGE_LLM_DAILY_ESTIMATED_TOKENS_PER_USER)
    charged = await db.execute(
        update(ExtractionDailyBudget)
        .where(
            ExtractionDailyBudget.user_id == owner_id,
            ExtractionDailyBudget.execution_day == execution_day,
            ExtractionDailyBudget.charged_tokens + estimate <= daily_limit,
        )
        .values(charged_tokens=ExtractionDailyBudget.charged_tokens + estimate)
    )
    if charged.rowcount != 1:
        raise ExtractionBudgetExceeded("daily extraction token budget exceeded")

    call = ExtractionCall(
        id=normalized_call_id,
        user_id=owner_id,
        run_id=extraction_run_id,
        unit_id=extraction_unit_id,
        lease_token=normalized_lease,
        execution_day=execution_day,
        estimated_tokens=estimate,
        charged_tokens=estimate,
        state="reserved",
        usage={},
        provider=normalized_provider,
        model=normalized_model,
        started_at=observed,
    )
    db.add(call)
    await db.flush()
    await _refresh_run_usage(db, extraction_run_id)
    return call


async def settle_extraction_call(
    db: AsyncSession,
    *,
    call_id: str,
    state: str,
    usage: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> bool:
    """Settle a reservation once and charge any reported excess exactly once."""

    _require_supported_database(db)
    normalized_state = str(state).strip().lower()
    if normalized_state not in _SETTLED_STATES:
        raise ValueError("state must be succeeded, failed, or unknown")
    normalized_call_id = str(call_id).strip()
    if not normalized_call_id:
        raise ValueError("call_id is required")
    observed = _observed_at(now)

    # Serialize actual-usage reconciliation with per-run reservations as well.
    # Lock order stays Run -> Call -> Day, including after cancellation/reclaim.
    await db.execute(update(KnowledgeExtractionRun).where(
        KnowledgeExtractionRun.id.in_(select(ExtractionCall.run_id).where(ExtractionCall.id == normalized_call_id)),
    ).values(updated_at=KnowledgeExtractionRun.updated_at).execution_options(synchronize_session=False))
    await db.execute(
        update(ExtractionCall)
        .where(ExtractionCall.id == normalized_call_id)
        .values(id=ExtractionCall.id)
    )
    # Settlement ignores lease ownership, but never changes the run outcome.
    call = await db.scalar(
        select(ExtractionCall)
        .where(ExtractionCall.id == normalized_call_id)
        .with_for_update().execution_options(populate_existing=True)
    )
    if call is None or call.state not in ('reserved', 'unknown'):
        return False
    if call.state == 'unknown' and normalized_state == 'unknown':
        return False

    sanitized_usage = _sanitize_usage(usage)
    actual_tokens = _reported_total_tokens(sanitized_usage)
    final_charge = max(int(call.estimated_tokens), int(call.charged_tokens), actual_tokens)
    excess = final_charge - int(call.charged_tokens)
    if excess > 0:
        await _ensure_daily_bucket(
            db,
            user_id=int(call.user_id),
            execution_day=call.execution_day,
        )
        # No cap condition here: actual usage is already incurred and must remain
        # visible.  Future reservations see this conservative overage.
        await db.execute(
            update(ExtractionDailyBudget)
            .where(
                ExtractionDailyBudget.user_id == int(call.user_id),
                ExtractionDailyBudget.execution_day == call.execution_day,
            )
            .values(charged_tokens=ExtractionDailyBudget.charged_tokens + excess)
        )
        call.charged_tokens = final_charge
    call.state = normalized_state
    call.usage = sanitized_usage
    call.finished_at = observed
    await db.flush()
    await _refresh_run_usage(db, call.run_id)
    return True
