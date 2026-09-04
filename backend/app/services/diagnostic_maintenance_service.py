"""Explicit, rollbackable cleanup for historical persisted diagnostics."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import AgentExecutionLog, AgentJob
from app.models.learner_model import ProjectionOutbox
from app.models.retrieval import RetrievalProjection
from app.utils.error_safety import redact_sensitive_text, safe_error_diagnostic


@dataclass
class DiagnosticCleanupSourceStats:
    """Bounded aggregate only; raw diagnostic content must never enter reports."""

    scanned_rows: int = 0
    changed_rows: int = 0
    changed_columns: int = 0


@dataclass
class DiagnosticCleanupReport:
    """Result of one dry-run or apply pass."""

    dry_run: bool
    sources: dict[str, DiagnosticCleanupSourceStats] = field(default_factory=dict)

    @property
    def scanned_rows(self) -> int:
        return sum(item.scanned_rows for item in self.sources.values())

    @property
    def changed_rows(self) -> int:
        return sum(item.changed_rows for item in self.sources.values())

    @property
    def changed_columns(self) -> int:
        return sum(item.changed_columns for item in self.sources.values())

    def as_dict(self) -> dict[str, Any]:
        return {
            "dry_run": self.dry_run,
            "scanned_rows": self.scanned_rows,
            "changed_rows": self.changed_rows,
            "changed_columns": self.changed_columns,
            "sources": {name: asdict(stats) for name, stats in self.sources.items()},
        }


def _safe_text(value: Any, *, max_chars: int) -> str:
    return redact_sensitive_text(value, max_chars=max_chars, fallback="operation_failed")


def _sanitize_diagnostic_mapping(value: Any, *, max_chars: int) -> tuple[Any, bool]:
    """Sanitize only known top-level diagnostic keys, never arbitrary payload data."""

    if not isinstance(value, dict):
        return value, False

    sanitized = dict(value)
    changed = False
    error_summary_changed = False
    for key in ("error", "error_summary", "last_error", "message", "reason", "summary"):
        current = sanitized.get(key)
        if not isinstance(current, str):
            continue
        safe = _safe_text(current, max_chars=max_chars)
        if safe == current:
            continue
        sanitized[key] = safe
        changed = True
        error_summary_changed = error_summary_changed or key == "error_summary"

    error_code = sanitized.get("error_code")
    if error_summary_changed and isinstance(error_code, str):
        diagnostic = safe_error_diagnostic(
            sanitized["error_summary"],
            code=error_code,
            max_chars=max_chars,
        )
        if sanitized.get("error_fingerprint") != diagnostic.fingerprint:
            sanitized["error_fingerprint"] = diagnostic.fingerprint
            changed = True

    return sanitized, changed


def _agent_job_changes(row: AgentJob) -> dict[str, Any]:
    changes: dict[str, Any] = {}
    if row.summary is not None:
        safe_summary = _safe_text(row.summary, max_chars=2000)
        if safe_summary != row.summary:
            changes["summary"] = safe_summary
    safe_result, result_changed = _sanitize_diagnostic_mapping(row.result, max_chars=2000)
    if result_changed:
        changes["result"] = safe_result
    return changes


def _agent_log_changes(row: AgentExecutionLog) -> dict[str, Any]:
    changes: dict[str, Any] = {}
    safe_message = _safe_text(row.message, max_chars=2000)
    if safe_message != row.message:
        changes["message"] = safe_message
    safe_metadata, metadata_changed = _sanitize_diagnostic_mapping(
        row.extra_metadata,
        max_chars=2000,
    )
    if metadata_changed:
        changes["extra_metadata"] = safe_metadata
    return changes


def _last_error_changes(row: Any, *, max_chars: int) -> dict[str, Any]:
    safe_error = _safe_text(row.last_error, max_chars=max_chars)
    return {"last_error": safe_error} if safe_error != row.last_error else {}


async def _clean_source(
    db: AsyncSession,
    *,
    model: Any,
    primary_key: Any,
    predicates: tuple[Any, ...],
    changes_for: Any,
    batch_size: int,
    dry_run: bool,
) -> DiagnosticCleanupSourceStats:
    stats = DiagnosticCleanupSourceStats()
    cursor: Any = None
    while True:
        statement = select(model).where(*predicates)
        if cursor is not None:
            statement = statement.where(primary_key > cursor)
        rows = list(
            (
                await db.scalars(
                    statement.order_by(primary_key.asc()).limit(batch_size)
                )
            ).all()
        )
        if not rows:
            break

        page_changed = False
        for row in rows:
            stats.scanned_rows += 1
            changes = changes_for(row)
            if not changes:
                continue
            stats.changed_rows += 1
            stats.changed_columns += len(changes)
            if dry_run:
                continue
            for attribute, value in changes.items():
                setattr(row, attribute, value)
            page_changed = True

        if page_changed:
            await db.flush()
        cursor = getattr(rows[-1], primary_key.key)

    return stats


async def sanitize_persisted_diagnostics(
    db: AsyncSession,
    *,
    dry_run: bool = True,
    batch_size: int = 250,
) -> DiagnosticCleanupReport:
    """Redact historical diagnostic columns without committing the transaction.

    ``dry_run`` is intentionally the default. Apply mode flushes each bounded
    page so validation errors surface early, while the caller retains the only
    authority to commit or roll back the complete maintenance pass.
    """

    normalized_batch_size = int(batch_size)
    if not 1 <= normalized_batch_size <= 5000:
        raise ValueError("batch_size must be between 1 and 5000")

    report = DiagnosticCleanupReport(dry_run=bool(dry_run))
    report.sources["agent_jobs"] = await _clean_source(
        db,
        model=AgentJob,
        primary_key=AgentJob.id,
        predicates=(
            AgentJob.status == "failed",
            or_(AgentJob.summary.is_not(None), AgentJob.result.is_not(None)),
        ),
        changes_for=_agent_job_changes,
        batch_size=normalized_batch_size,
        dry_run=dry_run,
    )
    report.sources["agent_execution_logs"] = await _clean_source(
        db,
        model=AgentExecutionLog,
        primary_key=AgentExecutionLog.id,
        predicates=(
            AgentExecutionLog.status.in_(("failed", "retrying")),
            AgentExecutionLog.message.is_not(None),
        ),
        changes_for=_agent_log_changes,
        batch_size=normalized_batch_size,
        dry_run=dry_run,
    )
    report.sources["projection_outbox"] = await _clean_source(
        db,
        model=ProjectionOutbox,
        primary_key=ProjectionOutbox.id,
        predicates=(ProjectionOutbox.last_error.is_not(None),),
        changes_for=lambda row: _last_error_changes(row, max_chars=2000),
        batch_size=normalized_batch_size,
        dry_run=dry_run,
    )
    report.sources["retrieval_projections"] = await _clean_source(
        db,
        model=RetrievalProjection,
        primary_key=RetrievalProjection.id,
        predicates=(RetrievalProjection.last_error.is_not(None),),
        changes_for=lambda row: _last_error_changes(row, max_chars=1000),
        batch_size=normalized_batch_size,
        dry_run=dry_run,
    )
    return report
