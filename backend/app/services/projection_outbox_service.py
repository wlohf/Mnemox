"""Durable, replayable learner-state projection outbox.

Rows are written in the same SQLAlchemy transaction as their source learning
event. Processing is deliberately small and deterministic: the worker reads a
user-owned event, projects linked evidence, and marks the row only after the
projection has flushed successfully.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import and_, case, func, or_, select, text, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.concept import Concept, ConceptLink
from app.models.learner_model import (
    ProjectionOutbox,
    ProjectionOutboxRetryPolicy,
    ProjectionOutboxWorkerHeartbeat,
)
from app.models.learning_event import LearningEvent
from app.services.learner_model_service import record_evidence, record_review_result_evidence

OUTBOX_MODEL_VERSION = "projection-outbox-v1"
REPLAY_PAGE_SIZE = 200
OUTBOX_LOCK_STALE_AFTER = timedelta(minutes=5)
OUTBOX_RETRY_POLICY_ID = 1
OUTBOX_RETRY_POLICY_CHANGED_KEY = "projection_outbox_retry_policy_changed"
# Shared for normal consumers and exclusive for a policy upgrade. Keeping the
# lock transaction-scoped lets normal projections run concurrently while an
# intentional retry-policy epoch change waits for in-flight projections.
POSTGRES_OUTBOX_RETRY_POLICY_LOCK_KEY = 0x4D4E4F5852504F4C
# PostgreSQL transaction advisory-lock namespace for user-scoped projection
# batches. It is distinct from the session-level migration lock namespace.
POSTGRES_PROJECTION_LOCK_NAMESPACE = 0x4D4E4F58


def _now() -> datetime:
    return datetime.now()


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.astimezone().replace(tzinfo=None) if parsed.tzinfo else parsed
    except (TypeError, ValueError):
        return None


def outbox_to_dict(row: ProjectionOutbox) -> dict[str, Any]:
    return {
        "id": row.id,
        "user_id": row.user_id,
        "concept_id": row.concept_id,
        "source_event_id": row.source_event_id,
        "idempotency_key": row.idempotency_key,
        "projection_type": row.projection_type,
        "model_version": row.model_version,
        "payload_version": row.payload_version,
        "payload": row.payload or {},
        "occurred_at": _iso(row.occurred_at),
        "status": row.status,
        "attempts": row.attempts,
        "available_at": _iso(row.available_at),
        "locked_at": _iso(row.locked_at),
        "processed_at": _iso(row.processed_at),
        "dead_lettered_at": _iso(row.dead_lettered_at),
        "last_error": row.last_error,
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
    }


def _terminal_failure_predicate():
    return ProjectionOutbox.dead_lettered_at.is_not(None)


def _retryable_failure_predicate(max_attempts: int):
    return and_(
        ProjectionOutbox.status == "failed",
        ProjectionOutbox.dead_lettered_at.is_(None),
        ProjectionOutbox.attempts < max(1, int(max_attempts)),
    )


async def _lock_outbox_retry_policy(
    db: AsyncSession,
    *,
    exclusive: bool,
) -> None:
    """Hold the retry-policy epoch lock for the current PostgreSQL transaction."""
    if db.bind is None or db.bind.dialect.name != "postgresql":
        return
    lock_function = (
        "pg_advisory_xact_lock"
        if exclusive
        else "pg_advisory_xact_lock_shared"
    )
    await db.execute(
        text(f"SELECT {lock_function}(CAST(:key AS BIGINT))"),
        {"key": POSTGRES_OUTBOX_RETRY_POLICY_LOCK_KEY},
    )


async def resolve_outbox_retry_policy(
    db: AsyncSession,
    *,
    max_attempts: int = 5,
    retry_policy_version: int = 1,
    now: datetime | None = None,
) -> int:
    """Resolve one versioned retry cap shared by every DLQ-aware consumer."""
    configured_attempts = max(1, int(max_attempts))
    configured_version = max(1, int(retry_policy_version))
    current = now or _now()
    db.info.pop(OUTBOX_RETRY_POLICY_CHANGED_KEY, None)

    async def _load_policy() -> ProjectionOutboxRetryPolicy | None:
        return await db.scalar(
            select(ProjectionOutboxRetryPolicy)
            .where(ProjectionOutboxRetryPolicy.id == OUTBOX_RETRY_POLICY_ID)
            .execution_options(populate_existing=True)
        )

    policy = await _load_policy()
    await _lock_outbox_retry_policy(
        db,
        exclusive=(policy is None or int(policy.policy_version) < configured_version),
    )
    # The lock is acquired after the initial read to avoid serializing steady
    # state consumers. Re-read under the lock because an upgrade may have won
    # that short race.
    policy = await _load_policy()
    if policy is None:
        values = {
            "id": OUTBOX_RETRY_POLICY_ID,
            "max_attempts": configured_attempts,
            "policy_version": configured_version,
            "updated_at": current,
        }
        dialect_name = db.bind.dialect.name if db.bind is not None else ""
        if dialect_name == "postgresql":
            statement = postgresql_insert(ProjectionOutboxRetryPolicy).values(**values).on_conflict_do_nothing(
                index_elements=["id"]
            )
            created = await db.execute(statement)
            if created.rowcount:
                db.info[OUTBOX_RETRY_POLICY_CHANGED_KEY] = True
        elif dialect_name == "sqlite":
            statement = sqlite_insert(ProjectionOutboxRetryPolicy).values(**values).on_conflict_do_nothing(
                index_elements=["id"]
            )
            created = await db.execute(statement)
            if created.rowcount:
                db.info[OUTBOX_RETRY_POLICY_CHANGED_KEY] = True
        else:
            db.add(ProjectionOutboxRetryPolicy(**values))
            await db.flush()
            db.info[OUTBOX_RETRY_POLICY_CHANGED_KEY] = True
        policy = await _load_policy()

    if policy is None:
        raise RuntimeError("无法初始化 projection outbox 重试策略")

    if int(policy.policy_version) < configured_version:
        updated = await db.execute(
            update(ProjectionOutboxRetryPolicy)
            .where(
                ProjectionOutboxRetryPolicy.id == OUTBOX_RETRY_POLICY_ID,
                ProjectionOutboxRetryPolicy.policy_version < configured_version,
            )
            .values(
                max_attempts=configured_attempts,
                policy_version=configured_version,
                updated_at=current,
            )
        )
        if updated.rowcount:
            db.info[OUTBOX_RETRY_POLICY_CHANGED_KEY] = True
        policy = await _load_policy()

    if policy is None:
        raise RuntimeError("无法读取 projection outbox 重试策略")
    if (
        int(policy.policy_version) == configured_version
        and int(policy.max_attempts) != configured_attempts
    ):
        raise ValueError(
            "retry policy version already uses a different max_attempts; "
            "increment OUTBOX_WORKER_RETRY_POLICY_VERSION before changing it"
        )
    return int(policy.max_attempts)


def consume_outbox_retry_policy_change(db: AsyncSession) -> bool:
    """Return whether resolving the policy changed durable shared state."""
    return bool(db.info.pop(OUTBOX_RETRY_POLICY_CHANGED_KEY, False))


async def get_outbox_retry_policy_state(
    db: AsyncSession,
) -> tuple[int, int] | None:
    """Read the durable retry policy without seeding or changing it."""
    policy = await db.scalar(
        select(ProjectionOutboxRetryPolicy)
        .where(ProjectionOutboxRetryPolicy.id == OUTBOX_RETRY_POLICY_ID)
        .execution_options(populate_existing=True)
    )
    if policy is None:
        return None
    return int(policy.max_attempts), int(policy.policy_version)


async def reconcile_outbox_terminal_failures(
    db: AsyncSession,
    *,
    max_attempts: int = 5,
    retry_policy_version: int = 1,
    resolve_retry_policy: bool = True,
    user_id: int | None = None,
    now: datetime | None = None,
) -> int:
    """Reconcile DLQ markers with the versioned shared retry policy.

    Historical rows do not retain the retry cap that applied when they failed,
    so the migration cannot classify them safely. The policy resolver gives
    every DLQ-aware worker the same cap, allowing safe bidirectional repair
    across a deliberate policy-version update.
    """
    current = now or _now()
    safe_max_attempts = (
        await resolve_outbox_retry_policy(
            db,
            max_attempts=max_attempts,
            retry_policy_version=retry_policy_version,
            now=current,
        )
        if resolve_retry_policy
        else max(1, int(max_attempts))
    )
    predicates = [
        ProjectionOutbox.status == "failed",
    ]
    if user_id is not None:
        predicates.append(ProjectionOutbox.user_id == int(user_id))

    reopened = await db.execute(
        update(ProjectionOutbox)
        .where(
            *predicates,
            ProjectionOutbox.dead_lettered_at.is_not(None),
            ProjectionOutbox.attempts < safe_max_attempts,
        )
        .values(
            dead_lettered_at=None,
            available_at=current,
            locked_at=None,
            updated_at=current,
        )
    )
    marked_terminal = await db.execute(
        update(ProjectionOutbox)
        .where(
            *predicates,
            ProjectionOutbox.dead_lettered_at.is_(None),
            ProjectionOutbox.attempts >= safe_max_attempts,
        )
        .values(
            dead_lettered_at=current,
            available_at=current,
            locked_at=None,
            updated_at=current,
        )
    )
    return int(reopened.rowcount or 0) + int(marked_terminal.rowcount or 0)


def _dead_letter_task_to_dict(row: ProjectionOutbox) -> dict[str, Any]:
    """Return a user-safe DLQ item without payload or internal exception text."""
    return {
        "id": row.id,
        "concept_id": row.concept_id,
        "projection_type": row.projection_type,
        "status": row.status,
        "attempts": row.attempts,
        "occurred_at": _iso(row.occurred_at),
        "dead_lettered_at": _iso(row.dead_lettered_at),
        "updated_at": _iso(row.updated_at),
    }


async def list_dead_letter_tasks(
    db: AsyncSession,
    user_id: int,
    *,
    max_attempts: int = 5,
    retry_policy_version: int = 1,
    offset: int = 0,
    limit: int = 50,
) -> dict[str, Any]:
    """List a user's terminally failed projection tasks for manual recovery."""
    safe_offset = max(0, int(offset))
    safe_limit = max(1, min(int(limit), 200))
    await reconcile_outbox_terminal_failures(
        db,
        user_id=int(user_id),
        max_attempts=max_attempts,
        retry_policy_version=retry_policy_version,
    )
    predicates = [
        ProjectionOutbox.user_id == int(user_id),
        _terminal_failure_predicate(),
    ]
    total = await db.scalar(select(func.count()).select_from(ProjectionOutbox).where(*predicates))
    rows = (
        await db.execute(
            select(ProjectionOutbox)
            .where(*predicates)
            .order_by(ProjectionOutbox.updated_at.desc(), ProjectionOutbox.id.desc())
            .offset(safe_offset)
            .limit(safe_limit)
        )
    ).scalars().all()
    return {
        "items": [_dead_letter_task_to_dict(row) for row in rows],
        "total": int(total or 0),
        "offset": safe_offset,
        "limit": safe_limit,
    }


async def retry_dead_letter_task(
    db: AsyncSession,
    user_id: int,
    outbox_id: int,
    *,
    max_attempts: int = 5,
    retry_policy_version: int = 1,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Return one owned terminal failure to the pending queue for a new attempt."""
    await reconcile_outbox_terminal_failures(
        db,
        user_id=int(user_id),
        max_attempts=max_attempts,
        retry_policy_version=retry_policy_version,
        now=now,
    )
    row = await db.scalar(
        select(ProjectionOutbox)
        .where(
            ProjectionOutbox.id == int(outbox_id),
            ProjectionOutbox.user_id == int(user_id),
        )
        .with_for_update()
    )
    if row is None:
        raise LookupError("投影任务不存在")
    if row.status != "failed" or row.dead_lettered_at is None:
        raise ValueError("投影任务尚未进入失败队列")

    current = now or _now()
    row.status = "pending"
    row.attempts = 0
    row.available_at = current
    row.locked_at = None
    row.processed_at = None
    row.dead_lettered_at = None
    row.last_error = None
    await db.flush()
    await db.refresh(row)
    return _dead_letter_task_to_dict(row)


async def record_outbox_worker_heartbeat(
    db: AsyncSession,
    *,
    worker_id: str,
    started_at: datetime | None = None,
    last_heartbeat_at: datetime | None = None,
    last_poll_at: datetime | None = None,
    last_success_at: datetime | None = None,
    last_error_at: datetime | None = None,
    last_projection_failure_at: datetime | None = None,
    stopped_at: datetime | None = None,
    now: datetime | None = None,
) -> None:
    """Upsert a non-sensitive durable worker heartbeat for cross-instance ops."""
    current = now or _now()
    clean_worker_id = str(worker_id or "").strip()[:120]
    if not clean_worker_id:
        raise ValueError("worker_id 不能为空")
    values = {
        "worker_id": clean_worker_id,
        "started_at": started_at or current,
        "last_heartbeat_at": last_heartbeat_at or current,
        "last_poll_at": last_poll_at,
        "last_success_at": last_success_at,
        "last_error_at": last_error_at,
        "last_projection_failure_at": last_projection_failure_at,
        "stopped_at": stopped_at,
        "updated_at": current,
    }
    dialect_name = db.bind.dialect.name if db.bind is not None else ""
    update_values = {key: value for key, value in values.items() if key != "worker_id"}
    if dialect_name == "postgresql":
        statement = postgresql_insert(ProjectionOutboxWorkerHeartbeat).values(**values).on_conflict_do_update(
            index_elements=["worker_id"],
            set_=update_values,
        )
    elif dialect_name == "sqlite":
        statement = sqlite_insert(ProjectionOutboxWorkerHeartbeat).values(**values).on_conflict_do_update(
            index_elements=["worker_id"],
            set_=update_values,
        )
    else:
        existing = await db.get(ProjectionOutboxWorkerHeartbeat, clean_worker_id)
        if existing is None:
            db.add(ProjectionOutboxWorkerHeartbeat(**values))
        else:
            for key, value in update_values.items():
                setattr(existing, key, value)
        await db.flush()
        return
    await db.execute(statement)
    await db.flush()


async def get_outbox_operations_snapshot(
    db: AsyncSession,
    *,
    max_attempts: int = 5,
    retry_policy_version: int = 1,
    now: datetime | None = None,
    backlog_count_threshold: int = 100,
    backlog_age_seconds: int = 900,
    terminal_failure_threshold: int = 1,
    stale_processing_threshold: int = 1,
    heartbeat_ttl_seconds: int = 30,
    worker_expected: bool = False,
    resolve_retry_policy: bool = True,
    reconcile_terminal_state: bool = True,
) -> dict[str, Any]:
    """Aggregate durable queue metrics shared by every application instance.

    Runtime counters belong to an individual worker process. This snapshot is
    intentionally calculated from ``projection_outbox`` so an operations
    probe observes the same backlog, terminal failures, and stale claims from
    every PostgreSQL application instance.
    """
    current = now or _now()
    if resolve_retry_policy:
        safe_max_attempts = await resolve_outbox_retry_policy(
            db,
            max_attempts=max_attempts,
            retry_policy_version=retry_policy_version,
            now=current,
        )
        policy_state = await get_outbox_retry_policy_state(db)
    else:
        policy_state = await get_outbox_retry_policy_state(db)
        safe_max_attempts = policy_state[0] if policy_state is not None else None
    if reconcile_terminal_state and safe_max_attempts is not None:
        await reconcile_outbox_terminal_failures(
            db,
            max_attempts=safe_max_attempts,
            retry_policy_version=retry_policy_version,
            resolve_retry_policy=False,
            now=current,
        )
    stale_before = current - OUTBOX_LOCK_STALE_AFTER
    if safe_max_attempts is None:
        terminal = and_(
            ProjectionOutbox.status == "failed",
            ProjectionOutbox.dead_lettered_at.is_not(None),
        )
        retryable = and_(
            ProjectionOutbox.status == "failed",
            ProjectionOutbox.dead_lettered_at.is_(None),
        )
    else:
        # The read-only metrics path derives state from the canonical cap so a
        # scrape never has to persist a legacy DLQ reconciliation.
        terminal = and_(
            ProjectionOutbox.status == "failed",
            ProjectionOutbox.attempts >= safe_max_attempts,
        )
        retryable = and_(
            ProjectionOutbox.status == "failed",
            ProjectionOutbox.attempts < safe_max_attempts,
        )
    stale_processing = and_(
        ProjectionOutbox.status == "processing",
        ProjectionOutbox.dead_lettered_at.is_(None),
        or_(
            ProjectionOutbox.locked_at.is_(None),
            ProjectionOutbox.locked_at < stale_before,
        ),
    )
    ready = or_(
        and_(
            ProjectionOutbox.status == "pending",
            ProjectionOutbox.dead_lettered_at.is_(None),
            ProjectionOutbox.available_at <= current,
        ),
        and_(retryable, ProjectionOutbox.available_at <= current),
    )
    active_queue = ProjectionOutbox.status.in_(("pending", "processing", "failed"))
    aggregates = (
        await db.execute(
            select(
                func.count().label("total"),
                func.coalesce(func.sum(case((ProjectionOutbox.status == "pending", 1), else_=0)), 0).label("pending"),
                func.coalesce(func.sum(case((retryable, 1), else_=0)), 0).label("retryable"),
                func.coalesce(func.sum(case((ProjectionOutbox.status == "processing", 1), else_=0)), 0).label("processing"),
                func.coalesce(func.sum(case((stale_processing, 1), else_=0)), 0).label("stale_processing"),
                func.coalesce(func.sum(case((terminal, 1), else_=0)), 0).label("dead_letter"),
                func.coalesce(func.sum(case((ready, 1), else_=0)), 0).label("ready"),
                func.min(case((ready, ProjectionOutbox.available_at), else_=None)).label("oldest_ready_at"),
            )
            .where(active_queue)
        )
    ).mappings().one()
    oldest_ready_at = aggregates["oldest_ready_at"]
    oldest_ready_age_seconds = (
        max(0, int((current - oldest_ready_at).total_seconds()))
        if oldest_ready_at is not None
        else None
    )
    heartbeat_cutoff = current - timedelta(seconds=max(1, int(heartbeat_ttl_seconds)))
    active_worker = and_(
        ProjectionOutboxWorkerHeartbeat.stopped_at.is_(None),
        ProjectionOutboxWorkerHeartbeat.last_heartbeat_at >= heartbeat_cutoff,
    )
    stale_worker = and_(
        ProjectionOutboxWorkerHeartbeat.stopped_at.is_(None),
        ProjectionOutboxWorkerHeartbeat.last_heartbeat_at < heartbeat_cutoff,
    )
    poll_error_worker = and_(
        active_worker,
        ProjectionOutboxWorkerHeartbeat.last_error_at.is_not(None),
        or_(
            ProjectionOutboxWorkerHeartbeat.last_success_at.is_(None),
            ProjectionOutboxWorkerHeartbeat.last_error_at
            > ProjectionOutboxWorkerHeartbeat.last_success_at,
        ),
        # ``last_error_at`` also records a batch that claimed a row but had a
        # projection-level failure. That is a queue/DLQ signal, not a broken
        # poller; only errors newer than the latest projection failure count.
        or_(
            ProjectionOutboxWorkerHeartbeat.last_projection_failure_at.is_(None),
            ProjectionOutboxWorkerHeartbeat.last_error_at
            > ProjectionOutboxWorkerHeartbeat.last_projection_failure_at,
        ),
    )
    worker_aggregates = (
        await db.execute(
            select(
                func.count().label("known_workers"),
                func.coalesce(func.sum(case((active_worker, 1), else_=0)), 0).label("active_workers"),
                func.coalesce(func.sum(case((stale_worker, 1), else_=0)), 0).label("stale_workers"),
                func.coalesce(func.sum(case((poll_error_worker, 1), else_=0)), 0).label("error_workers"),
            )
        )
    ).mappings().one()
    metrics = {
        "total": int(aggregates["total"] or 0),
        "pending": int(aggregates["pending"] or 0),
        "retryable": int(aggregates["retryable"] or 0),
        "processing": int(aggregates["processing"] or 0),
        "stale_processing": int(aggregates["stale_processing"] or 0),
        "dead_letter": int(aggregates["dead_letter"] or 0),
        "ready": int(aggregates["ready"] or 0),
        "oldest_ready_at": _iso(oldest_ready_at),
        "oldest_ready_age_seconds": oldest_ready_age_seconds,
        "known_workers": int(worker_aggregates["known_workers"] or 0),
        "active_workers": int(worker_aggregates["active_workers"] or 0),
        "stale_workers": int(worker_aggregates["stale_workers"] or 0),
        "error_workers": int(worker_aggregates["error_workers"] or 0),
        "retry_policy_initialized": int(policy_state is not None),
        "retry_policy_max_attempts": safe_max_attempts,
        "retry_policy_version": policy_state[1] if policy_state is not None else None,
        # A read-only operations probe must surface a deployment that changed
        # the retry cap without advancing the shared policy epoch. Consumers
        # still fail closed through ``resolve_outbox_retry_policy``.
        "retry_policy_config_conflict": int(
            policy_state is not None
            and policy_state[1] == max(1, int(retry_policy_version))
            and policy_state[0] != max(1, int(max_attempts))
        ),
    }
    alerts: list[dict[str, Any]] = []
    if policy_state is None:
        alerts.append(
            {
                "code": "projection_outbox_retry_policy_uninitialized",
                "severity": "critical",
                "count": 1,
            }
        )
    if metrics["retry_policy_config_conflict"]:
        alerts.append(
            {
                "code": "projection_outbox_retry_policy_config_conflict",
                "severity": "critical",
                "count": 1,
            }
        )
    if metrics["error_workers"]:
        alerts.append(
            {
                "code": "projection_outbox_worker_poll_error",
                "severity": "critical",
                "count": metrics["error_workers"],
            }
        )
    if metrics["dead_letter"] >= max(1, int(terminal_failure_threshold)):
        alerts.append(
            {
                "code": "projection_outbox_dead_letter",
                "severity": "critical",
                "count": metrics["dead_letter"],
            }
        )
    if metrics["stale_processing"] >= max(1, int(stale_processing_threshold)):
        alerts.append(
            {
                "code": "projection_outbox_stale_processing",
                "severity": "critical",
                "count": metrics["stale_processing"],
            }
        )
    if (
        metrics["ready"] >= max(1, int(backlog_count_threshold))
        and metrics["oldest_ready_age_seconds"] is not None
        and metrics["oldest_ready_age_seconds"] >= max(1, int(backlog_age_seconds))
    ):
        alerts.append(
            {
                "code": "projection_outbox_backlog_age",
                "severity": "warning",
                "count": metrics["ready"],
                "oldest_ready_age_seconds": metrics["oldest_ready_age_seconds"],
            }
        )
    if worker_expected and metrics["ready"] > 0 and metrics["active_workers"] == 0:
        alerts.append(
            {
                "code": "projection_outbox_no_active_worker",
                "severity": "critical",
                "count": metrics["ready"],
            }
        )
    return {
        "status": (
            "critical"
            if any(alert["severity"] == "critical" for alert in alerts)
            else "warning"
            if alerts
            else "healthy"
        ),
        "generated_at": _iso(current),
        "metrics": metrics,
        "retry_policy_version": policy_state[1] if policy_state is not None else None,
        "alerts": alerts,
    }


def render_outbox_prometheus_metrics(snapshot: dict[str, Any]) -> str:
    """Render only aggregate queue state for a protected scrape endpoint."""
    metrics = dict(snapshot.get("metrics") or {})
    names = {
        "total": "mnemox_projection_outbox_tasks",
        "pending": "mnemox_projection_outbox_pending_tasks",
        "retryable": "mnemox_projection_outbox_retryable_tasks",
        "processing": "mnemox_projection_outbox_processing_tasks",
        "stale_processing": "mnemox_projection_outbox_stale_processing_tasks",
        "dead_letter": "mnemox_projection_outbox_dead_letter_tasks",
        "ready": "mnemox_projection_outbox_ready_tasks",
        "oldest_ready_age_seconds": "mnemox_projection_outbox_oldest_ready_age_seconds",
        "known_workers": "mnemox_projection_outbox_known_workers",
        "active_workers": "mnemox_projection_outbox_active_workers",
        "stale_workers": "mnemox_projection_outbox_stale_workers",
        "error_workers": "mnemox_projection_outbox_error_workers",
        "retry_policy_initialized": "mnemox_projection_outbox_retry_policy_initialized",
        "retry_policy_max_attempts": "mnemox_projection_outbox_retry_policy_max_attempts",
        "retry_policy_version": "mnemox_projection_outbox_retry_policy_version",
        "retry_policy_config_conflict": "mnemox_projection_outbox_retry_policy_config_conflict",
    }
    lines = ["# TYPE mnemox_projection_outbox_alert gauge"]
    for key, name in names.items():
        value = metrics.get(key)
        if value is not None:
            lines.append(f"{name} {int(value)}")
    for alert in snapshot.get("alerts") or []:
        code = str(alert.get("code") or "unknown").replace('"', "")
        lines.append(f'mnemox_projection_outbox_alert{{code="{code}"}} 1')
    return "\n".join(lines) + "\n"


async def enqueue_projection(
    db: AsyncSession,
    user_id: int,
    source_event_id: int,
    *,
    concept_id: int | None = None,
    projection_type: str = "learner_state",
    idempotency_key: str | None = None,
    payload: dict[str, Any] | None = None,
    model_version: str = OUTBOX_MODEL_VERSION,
    occurred_at: datetime | None = None,
) -> dict[str, Any]:
    """Insert (or return) one outbox command, scoped to its owner."""
    event = await db.scalar(
        select(LearningEvent).where(LearningEvent.id == int(source_event_id), LearningEvent.user_id == int(user_id))
    )
    if event is None:
        raise LookupError("来源学习事件不存在")
    if concept_id is not None:
        owned = await db.scalar(select(Concept.id).where(Concept.id == int(concept_id), Concept.user_id == int(user_id)))
        if owned is None:
            raise LookupError("概念不存在")
    key = (idempotency_key or f"{projection_type}:{int(source_event_id)}:{int(concept_id) if concept_id is not None else '*'}")[:200]
    values = {
        "user_id": int(user_id),
        "concept_id": int(concept_id) if concept_id is not None else None,
        "source_event_id": int(source_event_id),
        "idempotency_key": key,
        "projection_type": str(projection_type)[:60],
        "model_version": str(model_version or OUTBOX_MODEL_VERSION)[:50],
        "payload_version": 1,
        "payload": dict(payload or {}),
        "occurred_at": occurred_at or event.timestamp or _now(),
        "status": "pending",
        "attempts": 0,
        "available_at": occurred_at or _now(),
    }
    dialect_name = db.bind.dialect.name if db.bind is not None else ""
    if dialect_name == "postgresql":
        statement = postgresql_insert(ProjectionOutbox).values(**values).on_conflict_do_nothing(
            constraint="uq_projection_outbox_user_key"
        )
    elif dialect_name == "sqlite":
        statement = sqlite_insert(ProjectionOutbox).values(**values).on_conflict_do_nothing(
            index_elements=["user_id", "idempotency_key"]
        )
    else:
        # Production and local development use PostgreSQL and SQLite. Keeping
        # the fallback explicit makes unsupported dialects fail at the unique
        # constraint instead of silently weakening the idempotency contract.
        statement = ProjectionOutbox.__table__.insert().values(**values)
    await db.execute(statement)
    row = await db.scalar(
        select(ProjectionOutbox).where(
            ProjectionOutbox.user_id == int(user_id),
            ProjectionOutbox.idempotency_key == key,
        )
    )
    if row is None:
        raise RuntimeError("outbox enqueue did not produce a readable row")
    return outbox_to_dict(row)


async def enqueue_for_learning_event(
    db: AsyncSession,
    event: LearningEvent | dict[str, Any],
    *,
    concept_id: int | None = None,
) -> dict[str, Any]:
    event_id = int(event["id"] if isinstance(event, dict) else event.id)
    user_id = int(event["user_id"] if isinstance(event, dict) else event.user_id)
    event_type = str(event["event_type"] if isinstance(event, dict) else event.event_type)
    event_payload = dict(event.get("payload") or event.get("event_data") or {}) if isinstance(event, dict) else dict(event.event_data or {})
    if concept_id is None:
        candidate = event_payload.get("concept_id")
        if isinstance(candidate, int) and candidate > 0:
            # Invalid/cross-user payload references are deliberately ignored;
            # the event remains durable and can be replayed after correction.
            owned = await db.scalar(
                select(Concept.id).where(
                    Concept.id == candidate,
                    Concept.user_id == user_id,
                )
            )
            if owned is not None:
                concept_id = int(candidate)
    return await enqueue_projection(
        db, user_id, event_id, concept_id=concept_id,
        idempotency_key=f"learner_state:{event_id}:{concept_id if concept_id is not None else '*'}",
        payload={"event_type": event_type, "concept_id": concept_id},
        occurred_at=(event.get("timestamp") if isinstance(event, dict) and isinstance(event.get("timestamp"), datetime) else (event.timestamp if not isinstance(event, dict) else None)),
    )


async def _project_event(
    db: AsyncSession,
    row: ProjectionOutbox,
    *,
    event: LearningEvent | None = None,
) -> int:
    if event is None:
        event = await db.scalar(
            select(LearningEvent).where(
                LearningEvent.id == row.source_event_id,
                LearningEvent.user_id == row.user_id,
            )
        )
    if event is None:
        raise LookupError("source event was deleted")
    payload = dict(event.event_data or {})
    event_type = str(event.event_type or "")
    if event_type == "learner.manual_override" and row.concept_id is not None:
        active = bool(payload.get("active"))
        mastery_estimate = payload.get("mastery_estimate")
        score = (
            max(0.0, min(1.0, float(mastery_estimate) / 100.0))
            if active and mastery_estimate is not None
            else 0.0
        )
        await record_evidence(
            db,
            row.user_id,
            row.concept_id,
            "manual_override",
            score=score,
            reliability=1.0,
            source_event_id=event.id,
            source_type="manual",
            source_id=str(event.id),
            dimension="overall",
            observed_at=event.timestamp or _now(),
            payload=payload,
        )
        return 1
    quality = payload.get("quality")
    if quality is not None and event_type in {"review.completed", "review_complete"}:
        quality = max(0, min(5, int(float(quality))))
        target_type = str(payload.get("target_type") or payload.get("item_type") or "")
        target_id = payload.get("target_id") or payload.get("item_id")
        if target_type and target_id is not None:
            return await record_review_result_evidence(
                db, row.user_id, target_type=target_type, target_id=int(target_id),
                quality=quality, source_event_id=event.id, observed_at=event.timestamp or _now(),
                next_review_at=_parse_datetime(payload.get("next_due_at")), concept_id=row.concept_id,
                normalized_score=(
                    float(payload["normalized_score"])
                    if payload.get("normalized_score") is not None
                    else None
                ),
            )
    if row.concept_id is None:
        return 0
    mapping = {
        "practice.answer": "answer",
        "practice.recall": "recall",
        "practice.explanation": "explanation",
        "practice.application": "application",
        "practice.hint": "hint_count",
        "study.duration": "study_duration",
        "study.frequency": "study_frequency",
        "study.repeated_question": "repeated_question",
        "study.interruption": "interruption",
        "study.recovery": "recovery",
    }
    evidence_type = mapping.get(event_type)
    if evidence_type is None:
        return 0
    raw_score = payload.get("score", payload.get("quality", 0.0))
    if evidence_type == "study_duration" and "score" not in payload:
        raw_score = min(1.0, max(0.0, float(payload.get("duration_minutes", 0.0)) / 25.0))
    score = float(raw_score)
    score = max(0.0, min(1.0, score if score <= 1 else score / 100.0))
    await record_evidence(
        db, row.user_id, row.concept_id, evidence_type, score=score, reliability=0.8,
        source_event_id=event.id, source_type=event.source or "projection",
        observed_at=event.timestamp or _now(), payload=payload,
    )
    return 1


def _is_noop_learner_state_projection(
    row: ProjectionOutbox,
    event: LearningEvent,
) -> bool:
    """Return whether a learner-state projection cannot write evidence."""
    if row.projection_type != "learner_state":
        return False
    return str(event.event_type or "") not in {
        "learner.manual_override",
        "review.completed",
        "review_complete",
        "practice.answer",
        "practice.recall",
        "practice.explanation",
        "practice.application",
        "practice.hint",
        "study.duration",
        "study.frequency",
        "study.repeated_question",
        "study.interruption",
        "study.recovery",
    }


async def _event_targets_concept(
    db: AsyncSession,
    event: LearningEvent,
    concept_id: int,
) -> bool:
    """Return whether an event explicitly belongs to one concept scope."""
    payload = dict(event.event_data or {})
    try:
        if int(payload.get("concept_id")) == int(concept_id):
            return True
    except (TypeError, ValueError):
        pass

    if str(event.event_type or "") not in {"review.completed", "review_complete"}:
        return False
    target_type = str(payload.get("target_type") or payload.get("item_type") or "").strip()
    target_id = payload.get("target_id") or payload.get("item_id")
    if not target_type or target_id is None:
        return False
    try:
        normalized_target_id = int(target_id)
    except (TypeError, ValueError):
        return False
    linked = await db.scalar(
        select(ConceptLink.id).where(
            ConceptLink.user_id == int(event.user_id),
            ConceptLink.concept_id == int(concept_id),
            ConceptLink.target_type == target_type,
            ConceptLink.target_id == normalized_target_id,
        )
    )
    return linked is not None


async def _lock_projection_users(
    db: AsyncSession,
    user_ids: list[int],
) -> None:
    """Serialize multi-row projection batches for each PostgreSQL user scope."""
    if not user_ids or db.bind is None or db.bind.dialect.name != "postgresql":
        return
    for lock_user_id in sorted({int(value) for value in user_ids}):
        await db.execute(
            text(
                "SELECT pg_advisory_xact_lock("
                "CAST(:namespace AS INTEGER), CAST(:user_id AS INTEGER))"
            ),
            {
                "namespace": POSTGRES_PROJECTION_LOCK_NAMESPACE,
                "user_id": lock_user_id,
            },
        )


async def process_outbox(
    db: AsyncSession,
    *,
    limit: int = 50,
    user_id: int | None = None,
    max_attempts: int = 5,
    retry_policy_version: int = 1,
    now: datetime | None = None,
    outbox_ids: list[int] | None = None,
    reconcile_terminal_state: bool = True,
    resolve_retry_policy: bool = True,
) -> dict[str, Any]:
    """Process pending and crash-stale rows; safe to call repeatedly."""
    current = now or _now()
    safe_max_attempts = (
        await resolve_outbox_retry_policy(
            db,
            max_attempts=max_attempts,
            retry_policy_version=retry_policy_version,
            now=current,
        )
        if resolve_retry_policy
        else max(1, int(max_attempts))
    )
    if reconcile_terminal_state:
        await reconcile_outbox_terminal_failures(
            db,
            user_id=user_id,
            max_attempts=safe_max_attempts,
            retry_policy_version=retry_policy_version,
            resolve_retry_policy=False,
            now=current,
        )
    stale_before = current - OUTBOX_LOCK_STALE_AFTER
    where = [
        or_(
            and_(
                ProjectionOutbox.status == "pending",
                ProjectionOutbox.dead_lettered_at.is_(None),
                ProjectionOutbox.attempts < safe_max_attempts,
                ProjectionOutbox.available_at <= current,
            ),
            and_(
                ProjectionOutbox.status == "processing",
                ProjectionOutbox.dead_lettered_at.is_(None),
                ProjectionOutbox.attempts < safe_max_attempts,
                ProjectionOutbox.locked_at < stale_before,
            ),
            and_(
                ProjectionOutbox.status == "failed",
                ProjectionOutbox.dead_lettered_at.is_(None),
                ProjectionOutbox.attempts < safe_max_attempts,
                ProjectionOutbox.available_at <= current,
            ),
        )
    ]
    if user_id is not None:
        # Take the user lock before row claims so concurrent API/replay calls
        # cannot acquire concept locks in contradictory batch orders.
        await _lock_projection_users(db, [int(user_id)])
        where.append(ProjectionOutbox.user_id == int(user_id))
    if outbox_ids is not None:
        if not outbox_ids:
            return {"claimed": 0, "processed": 0, "failed": 0}
        where.append(ProjectionOutbox.id.in_([int(value) for value in outbox_ids]))
    rows = (
        await db.execute(
            select(ProjectionOutbox)
            .where(*where)
            .order_by(ProjectionOutbox.id.asc())
            .limit(max(1, min(int(limit), 500)))
            .with_for_update(skip_locked=True)
        )
    ).scalars().all()
    if user_id is None:
        # Global consumers claim directly with SKIP LOCKED so peers can pass
        # over busy rows and continue with work for other users. A scoped
        # request skips a globally held row, so this does not form a blocking
        # row-lock/advisory-lock cycle.
        await _lock_projection_users(db, [int(row.user_id) for row in rows])
    events_by_id: dict[int, LearningEvent] = {}
    if rows:
        event_rows = (
            await db.execute(
                select(LearningEvent).where(
                    LearningEvent.id.in_([int(row.source_event_id) for row in rows])
                )
            )
        ).scalars().all()
        events_by_id = {int(event.id): event for event in event_rows}

    processed = failed = 0

    # Persist all claims before entering per-row savepoints. The row locks from
    # the query above remain held for the surrounding transaction, so flushing
    # once here preserves recovery semantics without one database round trip
    # per status transition.
    for row in rows:
        row.status = "processing"
        row.attempts = int(row.attempts or 0) + 1
        row.locked_at = current
    if rows:
        await db.flush()

    try:
        for row in rows:
            try:
                event = events_by_id.get(int(row.source_event_id))
                if event is not None and int(event.user_id) != int(row.user_id):
                    event = None
                if event is not None and _is_noop_learner_state_projection(row, event):
                    row.status = "processed"
                    row.processed_at = current
                    row.dead_lettered_at = None
                    row.last_error = None
                    processed += 1
                    continue
                async with db.begin_nested():
                    await _project_event(db, row, event=event)
                row.status = "processed"
                row.processed_at = current
                row.dead_lettered_at = None
                row.last_error = None
                processed += 1
            except Exception as exc:
                row.status = "failed"
                row.last_error = str(exc)[:2000]
                if int(row.attempts or 0) >= safe_max_attempts:
                    row.dead_lettered_at = current
                    row.available_at = current
                else:
                    row.dead_lettered_at = None
                    row.available_at = current + timedelta(seconds=min(300, 2 ** min(row.attempts, 8)))
                failed += 1
            finally:
                row.locked_at = None
    finally:
        if rows:
            await db.flush()
    return {"claimed": len(rows), "processed": processed, "failed": failed}


async def process_event_projection(
    db: AsyncSession,
    *,
    user_id: int,
    source_event_id: int,
    max_attempts: int = 5,
    retry_policy_version: int = 1,
) -> dict[str, int]:
    """Consume only one event's projection rows on the current request path."""
    outbox_ids = list(
        (
            await db.scalars(
                select(ProjectionOutbox.id)
                .where(
                    ProjectionOutbox.user_id == int(user_id),
                    ProjectionOutbox.source_event_id == int(source_event_id),
                )
                .order_by(ProjectionOutbox.id.asc())
            )
        ).all()
    )
    return await process_outbox(
        db,
        user_id=int(user_id),
        max_attempts=max_attempts,
        retry_policy_version=retry_policy_version,
        limit=max(1, len(outbox_ids)),
        outbox_ids=[int(value) for value in outbox_ids],
    )


async def replay_projections(
    db: AsyncSession,
    user_id: int,
    *,
    concept_id: int | None = None,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    reset_processed: bool = True,
    max_attempts: int = 5,
    retry_policy_version: int = 1,
) -> dict[str, Any]:
    """Queue and process a bounded, user-isolated event replay."""
    if start_at is not None and end_at is not None and start_at > end_at:
        raise ValueError("start_at 不能晚于 end_at")
    if concept_id is not None:
        owned = await db.scalar(
            select(Concept.id).where(
                Concept.id == int(concept_id),
                Concept.user_id == int(user_id),
            )
        )
        if owned is None:
            raise LookupError("概念不存在")
    predicates = [LearningEvent.user_id == int(user_id)]
    if start_at is not None:
        predicates.append(LearningEvent.timestamp >= start_at)
    if end_at is not None:
        predicates.append(LearningEvent.timestamp <= end_at)
    event_count = int(
        await db.scalar(
            select(func.count()).select_from(LearningEvent).where(*predicates)
        )
        or 0
    )
    totals = {"claimed": 0, "processed": 0, "failed": 0, "queued": 0}
    cursor_time: datetime | None = None
    cursor_id = 0

    while True:
        page_predicates = list(predicates)
        if cursor_time is not None:
            page_predicates.append(
                or_(
                    LearningEvent.timestamp > cursor_time,
                    and_(
                        LearningEvent.timestamp == cursor_time,
                        LearningEvent.id > cursor_id,
                    ),
                )
            )
        events = (
            await db.execute(
                select(LearningEvent)
                .where(*page_predicates)
                .order_by(LearningEvent.timestamp.asc(), LearningEvent.id.asc())
                .limit(REPLAY_PAGE_SIZE)
            )
        ).scalars().all()
        if not events:
            break

        selected_ids: list[int] = []
        for event in events:
            if concept_id is not None and not await _event_targets_concept(db, event, int(concept_id)):
                continue
            item = await enqueue_for_learning_event(db, event, concept_id=concept_id)
            selected_ids.append(int(item["id"]))
        if reset_processed and selected_ids:
            await db.execute(
                update(ProjectionOutbox)
                .where(
                    ProjectionOutbox.user_id == int(user_id),
                    ProjectionOutbox.id.in_(selected_ids),
                )
                .values(
                    status="pending",
                    attempts=0,
                    locked_at=None,
                    processed_at=None,
                    dead_lettered_at=None,
                    last_error=None,
                    available_at=_now(),
                )
            )
        page_result = await process_outbox(
            db,
            user_id=int(user_id),
            max_attempts=max_attempts,
            retry_policy_version=retry_policy_version,
            limit=REPLAY_PAGE_SIZE,
            outbox_ids=selected_ids,
        )
        totals["queued"] += len(selected_ids)
        for key in ("claimed", "processed", "failed"):
            totals[key] += int(page_result[key])

        last_event = events[-1]
        cursor_time = last_event.timestamp
        cursor_id = int(last_event.id)
        if len(events) < REPLAY_PAGE_SIZE:
            break

    totals.update(
        {
            "events": event_count,
            "user_id": int(user_id),
            "concept_id": concept_id,
        }
    )
    return totals
