"""Lifecycle-managed consumer for durable knowledge extraction runs."""
from __future__ import annotations

import asyncio
import logging
import os
import socket
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.services.knowledge_extraction_service import (
    claim_next_extraction_run,
    mark_extraction_run_failed,
    process_claimed_extraction_run,
)
from app.utils.error_safety import safe_exception_summary


logger = logging.getLogger(__name__)


def default_extraction_worker_id() -> str:
    host = str(socket.gethostname() or "worker").strip() or "worker"
    return f"knowledge:{host}:{os.getpid()}:{uuid.uuid4().hex[:10]}"[:120]


class KnowledgeExtractionWorker:
    """Claim one durable run at a time and commit its isolated outcome."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        worker_id: str | None = None,
        poll_interval_seconds: float = 2.0,
        batch_size: int = 4,
        max_attempts: int = 5,
        lease_seconds: int = 120,
        retry_base_seconds: float = 5.0,
    ) -> None:
        if poll_interval_seconds <= 0:
            raise ValueError("poll_interval_seconds 必须大于 0")
        if batch_size < 1 or max_attempts < 1 or lease_seconds < 1:
            raise ValueError("worker batch、attempt 和 lease 配置必须大于 0")
        self._session_factory = session_factory
        self.worker_id = (worker_id or default_extraction_worker_id())[:120]
        self._poll_interval_seconds = float(poll_interval_seconds)
        self._batch_size = int(batch_size)
        self._max_attempts = int(max_attempts)
        self._lease_seconds = int(lease_seconds)
        self._retry_base_seconds = max(0.0, float(retry_base_seconds))
        self._stop_event = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._running = False
        self._polls = 0
        self._claimed = 0
        self._succeeded = 0
        self._partial = 0
        self._failed = 0
        self._last_error: str | None = None

    def snapshot(self) -> dict[str, Any]:
        return {
            "running": self._running,
            "polls": self._polls,
            "claimed": self._claimed,
            "succeeded": self._succeeded,
            "partial": self._partial,
            "failed": self._failed,
            "last_error": self._last_error,
            "poll_interval_seconds": self._poll_interval_seconds,
        }

    def health_snapshot(self) -> dict[str, Any]:
        result = self.snapshot()
        result.pop("last_error", None)
        return result

    async def _claim_one(self) -> tuple[int, int] | None:
        async with self._session_factory() as session:
            try:
                run = await claim_next_extraction_run(
                    session,
                    worker_id=self.worker_id,
                    max_attempts=self._max_attempts,
                    lease_seconds=self._lease_seconds,
                )
                if run is None:
                    await session.rollback()
                    return None
                identity = (int(run.id), int(run.attempt_count or 1))
                await session.commit()
                return identity
            except BaseException:
                await session.rollback()
                raise

    async def _finish_one(self, run_id: int):
        async with self._session_factory() as session:
            try:
                run = await process_claimed_extraction_run(
                    session,
                    run_id=int(run_id),
                    worker_id=self.worker_id,
                )
                status = str(run.status)
                await session.commit()
                return status
            except BaseException:
                await session.rollback()
                raise

    async def _record_failure(self, run_id: int, attempt_count: int, exc: BaseException) -> None:
        delay = self._retry_base_seconds * (2 ** max(0, int(attempt_count) - 1))
        async with self._session_factory() as session:
            try:
                await mark_extraction_run_failed(
                    session,
                    run_id=int(run_id),
                    worker_id=self.worker_id,
                    error=exc,
                    retry_delay_seconds=delay,
                )
                await session.commit()
            except BaseException:
                await session.rollback()
                raise

    async def run_once(self) -> dict[str, int]:
        totals = {"claimed": 0, "succeeded": 0, "partial": 0, "failed": 0}
        for _ in range(self._batch_size):
            claimed = await self._claim_one()
            if claimed is None:
                break
            run_id, attempt_count = claimed
            totals["claimed"] += 1
            try:
                status = await self._finish_one(run_id)
                if status == "succeeded":
                    totals["succeeded"] += 1
                elif status == "partial":
                    totals["partial"] += 1
            except Exception as exc:
                totals["failed"] += 1
                self._last_error = safe_exception_summary(exc)
                await self._record_failure(run_id, attempt_count, exc)
                logger.warning(
                    "knowledge extraction failed run_id=%s error=%s",
                    run_id,
                    self._last_error,
                )
        self._polls += 1
        self._claimed += totals["claimed"]
        self._succeeded += totals["succeeded"]
        self._partial += totals["partial"]
        self._failed += totals["failed"]
        if not totals["failed"]:
            self._last_error = None
        return totals

    def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._stop_event.clear()
        self._running = True
        self._task = asyncio.create_task(self._run(), name=f"knowledge-extraction:{self.worker_id}")

    async def stop(self) -> None:
        self._stop_event.set()
        if self._task is not None and self._task is not asyncio.current_task():
            await self._task
        self._task = None
        self._running = False

    async def _run(self) -> None:
        try:
            while not self._stop_event.is_set():
                try:
                    await self.run_once()
                except Exception as exc:
                    self._last_error = safe_exception_summary(exc)
                    logger.warning("knowledge extraction poll failed: %s", self._last_error)
                try:
                    await asyncio.wait_for(
                        self._stop_event.wait(),
                        timeout=self._poll_interval_seconds,
                    )
                except asyncio.TimeoutError:
                    continue
        finally:
            self._running = False
