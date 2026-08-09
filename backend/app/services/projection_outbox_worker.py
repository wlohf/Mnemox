"""Lifecycle-managed consumer for durable projection outbox rows."""
from __future__ import annotations

import asyncio
import os
import socket
from datetime import datetime
import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.services.projection_outbox_service import process_outbox


logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now()


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def default_worker_id() -> str:
    """Return an operational identifier without using user or event data."""
    return f"{socket.gethostname()}:{os.getpid()}"


class ProjectionOutboxWorker:
    """Poll and commit projection batches until the application shuts down."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        worker_id: str | None = None,
        batch_size: int = 50,
        max_attempts: int = 5,
        poll_interval_seconds: float = 2.0,
    ) -> None:
        if batch_size < 1:
            raise ValueError("batch_size 必须大于 0")
        if max_attempts < 1:
            raise ValueError("max_attempts 必须大于 0")
        if poll_interval_seconds <= 0:
            raise ValueError("poll_interval_seconds 必须大于 0")

        self._session_factory = session_factory
        self.worker_id = (worker_id or default_worker_id()).strip()[:120] or default_worker_id()
        self._batch_size = int(batch_size)
        self._max_attempts = int(max_attempts)
        self._poll_interval_seconds = float(poll_interval_seconds)
        self._stop_event = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
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

    async def _process_one_row(self) -> dict[str, int]:
        """Claim and persist one row, retaining no locks between projections."""
        async with self._session_factory() as session:
            try:
                result = await process_outbox(
                    session,
                    limit=1,
                    max_attempts=self._max_attempts,
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
        self._task = asyncio.create_task(
            self._run(),
            name=f"projection-outbox-worker:{self.worker_id}",
        )

    async def stop(self) -> None:
        """Wake the poller and wait for its current database transaction to finish."""
        self._stop_event.set()
        task = self._task
        if task is not None and task is not asyncio.current_task():
            await task
        self._task = None
        self._running = False

    async def _run(self) -> None:
        try:
            while not self._stop_event.is_set():
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
                    self._failed_polls += 1
                    self._last_error_at = _now()
                    self._last_error = str(exc)[:500]
                    logger.warning(
                        "projection outbox poll failed worker_id=%s error=%s",
                        self.worker_id,
                        exc,
                        exc_info=True,
                    )

                try:
                    await asyncio.wait_for(
                        self._stop_event.wait(),
                        timeout=self._poll_interval_seconds,
                    )
                except asyncio.TimeoutError:
                    pass
        finally:
            self._running = False
