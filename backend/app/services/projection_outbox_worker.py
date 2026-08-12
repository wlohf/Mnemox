"""Lifecycle-managed consumer for durable projection outbox rows."""
from __future__ import annotations

import asyncio
import os
import socket
import uuid
from datetime import datetime
import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.services.projection_outbox_service import (
    consume_outbox_retry_policy_change,
    get_outbox_operations_snapshot,
    process_outbox,
    reconcile_outbox_terminal_failures,
    record_outbox_worker_heartbeat,
    resolve_outbox_retry_policy,
)


logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now()


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def default_worker_id(prefix: str | None = None) -> str:
    """Return one durable runtime ID without using user or event data."""
    token = uuid.uuid4().hex[:12]
    runtime_suffix = f":{os.getpid()}:{token}"
    clean_prefix = str(prefix or "").strip().strip(":")
    if clean_prefix:
        available_prefix = max(1, 120 - len(runtime_suffix))
        return f"{clean_prefix[:available_prefix]}{runtime_suffix}"
    host = str(socket.gethostname() or "worker").strip().strip(":") or "worker"
    available_host = max(1, 120 - len(runtime_suffix))
    return f"{host[:available_host]}{runtime_suffix}"


class ProjectionOutboxWorker:
    """Poll and commit projection batches until the application shuts down."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        worker_id: str | None = None,
        batch_size: int = 50,
        max_attempts: int = 5,
        retry_policy_version: int = 1,
        poll_interval_seconds: float = 2.0,
        heartbeat_enabled: bool = False,
        heartbeat_interval_seconds: float = 15.0,
        heartbeat_ttl_seconds: int = 45,
        alert_backlog_count_threshold: int = 100,
        alert_backlog_age_seconds: int = 900,
        alert_terminal_failure_threshold: int = 1,
        alert_stale_processing_threshold: int = 1,
    ) -> None:
        if batch_size < 1:
            raise ValueError("batch_size 必须大于 0")
        if max_attempts < 1:
            raise ValueError("max_attempts 必须大于 0")
        if retry_policy_version < 1:
            raise ValueError("retry_policy_version 必须大于 0")
        if poll_interval_seconds <= 0:
            raise ValueError("poll_interval_seconds 必须大于 0")
        if heartbeat_interval_seconds <= 0:
            raise ValueError("heartbeat_interval_seconds 必须大于 0")
        if heartbeat_ttl_seconds < 1:
            raise ValueError("heartbeat_ttl_seconds 必须大于 0")
        minimum_heartbeat_ttl = heartbeat_interval_seconds + max(
            5.0,
            heartbeat_interval_seconds * 0.25,
        )
        if heartbeat_enabled and heartbeat_ttl_seconds < minimum_heartbeat_ttl:
            raise ValueError(
                "heartbeat_ttl_seconds 必须至少大于心跳间隔并保留调度余量"
            )

        self._session_factory = session_factory
        self.worker_id = (worker_id or default_worker_id()).strip()[:120] or default_worker_id()
        self._batch_size = int(batch_size)
        self._max_attempts = int(max_attempts)
        self._retry_policy_version = int(retry_policy_version)
        self._poll_interval_seconds = float(poll_interval_seconds)
        self._heartbeat_enabled = bool(heartbeat_enabled)
        self._heartbeat_interval_seconds = float(heartbeat_interval_seconds)
        self._heartbeat_ttl_seconds = int(heartbeat_ttl_seconds)
        self._alert_backlog_count_threshold = int(alert_backlog_count_threshold)
        self._alert_backlog_age_seconds = int(alert_backlog_age_seconds)
        self._alert_terminal_failure_threshold = int(alert_terminal_failure_threshold)
        self._alert_stale_processing_threshold = int(alert_stale_processing_threshold)
        self._stop_event = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._heartbeat_task: asyncio.Task[None] | None = None
        self._alert_task: asyncio.Task[None] | None = None
        self._running = False
        self._started_at: datetime | None = None
        self._last_poll_at: datetime | None = None
        self._last_success_at: datetime | None = None
        self._last_error_at: datetime | None = None
        self._last_projection_failure_at: datetime | None = None
        self._last_error: str | None = None
        self._polls = 0
        self._failed_polls = 0
        self._claimed = 0
        self._processed = 0
        self._failed = 0
        self._last_heartbeat_at: datetime | None = None
        self._active_alert_codes: frozenset[str] = frozenset()

    def snapshot(self) -> dict[str, Any]:
        """Return aggregate worker state suitable for a health response."""
        return {
            "worker_id": self.worker_id,
            "running": self._running,
            "started_at": _iso(self._started_at),
            "last_poll_at": _iso(self._last_poll_at),
            "last_success_at": _iso(self._last_success_at),
            "last_error_at": _iso(self._last_error_at),
            "last_projection_failure_at": _iso(self._last_projection_failure_at),
            "last_error": self._last_error,
            "polls": self._polls,
            "failed_polls": self._failed_polls,
            "claimed": self._claimed,
            "processed": self._processed,
            "failed": self._failed,
        }

    def health_snapshot(self) -> dict[str, Any]:
        """Return operational counters without exposing host or exception details."""
        snapshot = self.snapshot()
        snapshot.pop("worker_id", None)
        snapshot.pop("last_error", None)
        return snapshot

    async def run_once(self) -> dict[str, int]:
        """Process up to one configured batch, committing each claimed row alone."""
        self._last_poll_at = _now()
        totals = {"claimed": 0, "processed": 0, "failed": 0}
        try:
            await self._reconcile_terminal_failures()
            for _ in range(self._batch_size):
                result = await self._process_one_row()
                for key in totals:
                    totals[key] += int(result[key])
                if not result["claimed"]:
                    break
        except BaseException:
            self._polls += 1
            raise

        self._polls += 1
        self._claimed += totals["claimed"]
        self._processed += totals["processed"]
        self._failed += totals["failed"]
        self._last_success_at = _now()
        if totals["failed"]:
            failure_at = _now()
            self._last_projection_failure_at = failure_at
            self._last_error_at = failure_at
            self._last_error = "one or more projection rows failed"
        else:
            self._last_error = None
        return totals

    async def _reconcile_terminal_failures(self) -> int:
        """Resolve the shared cap and reconcile DLQ state before each poll."""
        async with self._session_factory() as session:
            try:
                effective_max_attempts = await resolve_outbox_retry_policy(
                    session,
                    max_attempts=self._max_attempts,
                    retry_policy_version=self._retry_policy_version,
                )
                reconciled = await reconcile_outbox_terminal_failures(
                    session,
                    max_attempts=effective_max_attempts,
                    retry_policy_version=self._retry_policy_version,
                    resolve_retry_policy=False,
                )
                if reconciled or consume_outbox_retry_policy_change(session):
                    await session.commit()
                else:
                    await session.rollback()
                return effective_max_attempts
            except BaseException:
                await session.rollback()
                raise

    async def _process_one_row(self) -> dict[str, int]:
        """Claim and persist one row, retaining no locks between projections."""
        async with self._session_factory() as session:
            try:
                result = await process_outbox(
                    session,
                    limit=1,
                    max_attempts=self._max_attempts,
                    retry_policy_version=self._retry_policy_version,
                    reconcile_terminal_state=False,
                )
                if result["claimed"]:
                    await session.commit()
                else:
                    await session.rollback()
            except BaseException:
                await session.rollback()
                raise
        return {
            "claimed": int(result["claimed"]),
            "processed": int(result["processed"]),
            "failed": int(result["failed"]),
        }

    def start(self) -> None:
        """Start a single polling task if this process has not already started it."""
        if self._task is not None and not self._task.done():
            return
        self._stop_event.clear()
        self._running = True
        self._started_at = _now()
        if self._heartbeat_enabled:
            self._heartbeat_task = asyncio.create_task(
                self._run_heartbeat(),
                name=f"projection-outbox-heartbeat:{self.worker_id}",
            )
        self._task = asyncio.create_task(
            self._run(),
            name=f"projection-outbox-worker:{self.worker_id}",
        )

    async def stop(self) -> None:
        """Wake the poller and wait for its current database transaction to finish."""
        self._stop_event.set()
        task = self._task
        heartbeat_task = self._heartbeat_task
        if task is not None and task is not asyncio.current_task():
            await task
        if heartbeat_task is not None and heartbeat_task is not asyncio.current_task():
            await heartbeat_task
        alert_task = self._alert_task
        if alert_task is not None and alert_task is not asyncio.current_task():
            await alert_task
        self._task = None
        self._heartbeat_task = None
        self._alert_task = None
        self._running = False
        await self._persist_heartbeat(stopped_at=_now(), force=True)

    async def _persist_heartbeat(
        self,
        *,
        stopped_at: datetime | None = None,
        force: bool = False,
    ) -> bool:
        """Persist worker liveness independently from projection transactions."""
        if not self._heartbeat_enabled:
            return False
        current = _now()
        if (
            not force
            and self._last_heartbeat_at is not None
            and (current - self._last_heartbeat_at).total_seconds() < self._heartbeat_interval_seconds
        ):
            return False
        try:
            async with self._session_factory() as session:
                await record_outbox_worker_heartbeat(
                    session,
                    worker_id=self.worker_id,
                    started_at=self._started_at,
                    last_heartbeat_at=current,
                    last_poll_at=self._last_poll_at,
                    last_success_at=self._last_success_at,
                    last_error_at=self._last_error_at,
                    last_projection_failure_at=self._last_projection_failure_at,
                    stopped_at=stopped_at,
                    now=current,
                )
                await session.commit()
        except Exception as exc:
            logger.warning(
                "projection outbox heartbeat failed worker_id=%s error=%s",
                self.worker_id,
                exc,
                exc_info=True,
            )
            return False
        self._last_heartbeat_at = current
        return True

    async def _emit_alert_transition(self) -> None:
        """Log aggregate alert changes for deployment log-based alerting."""
        if not self._heartbeat_enabled:
            return
        try:
            async with self._session_factory() as session:
                snapshot = await get_outbox_operations_snapshot(
                    session,
                    max_attempts=self._max_attempts,
                    retry_policy_version=self._retry_policy_version,
                    backlog_count_threshold=self._alert_backlog_count_threshold,
                    backlog_age_seconds=self._alert_backlog_age_seconds,
                    terminal_failure_threshold=self._alert_terminal_failure_threshold,
                    stale_processing_threshold=self._alert_stale_processing_threshold,
                    heartbeat_ttl_seconds=self._heartbeat_ttl_seconds,
                    worker_expected=True,
                    # Alert scans must remain observable when this deployment
                    # has drifted from the durable retry-policy epoch. The
                    # consuming path still raises and retries the next poll.
                    resolve_retry_policy=False,
                    reconcile_terminal_state=False,
                )
                await session.rollback()
        except Exception as exc:
            logger.warning(
                "projection outbox alert snapshot failed worker_id=%s error=%s",
                self.worker_id,
                exc,
                exc_info=True,
            )
            return
        current_codes = frozenset(
            str(alert["code"])
            for alert in snapshot.get("alerts", [])
            if alert.get("severity") in {"warning", "critical"}
        )
        if current_codes == self._active_alert_codes:
            return
        if current_codes:
            logger.error(
                "projection outbox alert transition worker_id=%s codes=%s",
                self.worker_id,
                sorted(current_codes),
            )
        elif self._active_alert_codes:
            logger.info(
                "projection outbox alerts recovered worker_id=%s",
                self.worker_id,
            )
        self._active_alert_codes = current_codes

    def _schedule_alert_transition(self) -> None:
        """Run one aggregate alert scan without delaying durable heartbeats."""
        if self._stop_event.is_set():
            return
        if self._alert_task is None or self._alert_task.done():
            self._alert_task = asyncio.create_task(
                self._emit_alert_transition(),
                name=f"projection-outbox-alerts:{self.worker_id}",
            )

    async def _run_heartbeat(self) -> None:
        """Refresh liveness independently while a slow projection batch runs."""
        while not self._stop_event.is_set():
            if await self._persist_heartbeat(force=True):
                self._schedule_alert_transition()
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=self._heartbeat_interval_seconds,
                )
            except asyncio.TimeoutError:
                pass

    async def _run(self) -> None:
        try:
            while not self._stop_event.is_set():
                poll_failed = False
                try:
                    result = await self.run_once()
                    if result["claimed"]:
                        logger.info(
                            "projection outbox batch worker_id=%s claimed=%s processed=%s failed=%s",
                            self.worker_id,
                            result["claimed"],
                            result["processed"],
                            result["failed"],
                        )
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    poll_failed = True
                    self._failed_polls += 1
                    self._last_error_at = _now()
                    self._last_error = str(exc)[:500]
                    logger.warning(
                        "projection outbox poll failed worker_id=%s error=%s",
                        self.worker_id,
                        exc,
                        exc_info=True,
                    )

                if poll_failed and await self._persist_heartbeat(force=True):
                    self._schedule_alert_transition()

                try:
                    await asyncio.wait_for(
                        self._stop_event.wait(),
                        timeout=self._poll_interval_seconds,
                    )
                except asyncio.TimeoutError:
                    pass
        finally:
            self._running = False
