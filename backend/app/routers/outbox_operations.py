"""Private, aggregate-only projection outbox monitoring endpoint."""
from __future__ import annotations

import hmac

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import _is_sqlite, get_db
from app.services.projection_outbox_service import (
    get_outbox_operations_snapshot,
    render_outbox_prometheus_metrics,
)


router = APIRouter(include_in_schema=False)


def _require_operations_token(token: str | None) -> None:
    configured = settings.OUTBOX_OPS_TOKEN.strip()
    if not configured or not token or not hmac.compare_digest(token, configured):
        # Match a missing route so deployments do not advertise an internal
        # monitoring surface when no operations secret is configured.
        raise HTTPException(status_code=404, detail="Not found")


@router.get("/metrics", response_class=PlainTextResponse)
async def projection_outbox_metrics(
    x_mnemox_ops_token: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> PlainTextResponse:
    """Expose only global numeric outbox metrics for an internal scraper."""
    _require_operations_token(x_mnemox_ops_token)
    snapshot = await get_outbox_operations_snapshot(
        db,
        max_attempts=settings.OUTBOX_WORKER_MAX_ATTEMPTS,
        retry_policy_version=settings.OUTBOX_WORKER_RETRY_POLICY_VERSION,
        backlog_count_threshold=settings.OUTBOX_ALERT_BACKLOG_COUNT_THRESHOLD,
        backlog_age_seconds=settings.OUTBOX_ALERT_BACKLOG_AGE_SECONDS,
        terminal_failure_threshold=settings.OUTBOX_ALERT_TERMINAL_FAILURE_THRESHOLD,
        stale_processing_threshold=settings.OUTBOX_ALERT_STALE_PROCESSING_THRESHOLD,
        heartbeat_ttl_seconds=settings.OUTBOX_WORKER_HEARTBEAT_TTL_SECONDS,
        worker_expected=bool(settings.OUTBOX_WORKER_ENABLED and not _is_sqlite()),
        resolve_retry_policy=False,
        reconcile_terminal_state=False,
    )
    return PlainTextResponse(render_outbox_prometheus_metrics(snapshot))
