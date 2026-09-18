"""Lifecycle-managed extraction consumer with bounded cancellation/shutdown."""
from __future__ import annotations

import asyncio
import logging
import os
import socket
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import settings
from app.services.extraction_budget_service import ExtractionLeaseLost
from app.services.knowledge_extraction_service import (
    claim_next_extraction_run, mark_extraction_run_failed, process_claimed_extraction_run,
    recover_expired_extraction_runs, release_extraction_run,
)
from app.utils.error_safety import safe_exception_summary

logger = logging.getLogger(__name__)


def default_extraction_worker_id() -> str:
    host = str(socket.gethostname() or 'worker').strip() or 'worker'
    return f'knowledge:{host}:{os.getpid()}:{uuid.uuid4().hex[:10]}'[:120]


class KnowledgeExtractionWorker:
    """Claim leases durably; the runtime checkpoints each Unit independently."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession], *, worker_id=None,
                 poll_interval_seconds=2.0, batch_size=4, max_attempts=5,
                 lease_seconds=120, retry_base_seconds=5.0, shutdown_grace_seconds=None):
        if poll_interval_seconds <= 0 or min(batch_size, max_attempts, lease_seconds) <= 0:
            raise ValueError('worker poll、batch、attempt 和 lease 配置必须大于 0')
        self._session_factory = session_factory
        self.worker_id = (worker_id or default_extraction_worker_id())[:120]
        self._poll_interval_seconds = float(poll_interval_seconds)
        self._batch_size = int(batch_size)
        self._max_attempts = int(max_attempts)
        self._lease_seconds = float(lease_seconds)
        self._retry_base_seconds = max(0.0, float(retry_base_seconds))
        self._shutdown_grace = float(shutdown_grace_seconds if shutdown_grace_seconds is not None
                                     else settings.KNOWLEDGE_EXTRACTION_SHUTDOWN_GRACE_SECONDS)
        if self._shutdown_grace <= 0:
            raise ValueError('shutdown grace 必须大于 0')
        self._stop_event = asyncio.Event()
        self._task = None
        self._running = False
        self._polls = self._claimed = self._succeeded = self._partial = self._failed = self._fenced = 0
        self._last_error = None
        self._orphan_tasks = set()
        self._pass_lock = asyncio.Lock()

    def snapshot(self) -> dict[str, Any]:
        return {
            'running': self._running,
            'stopping': bool(self._stop_event.is_set() and self._task and not self._task.done()),
            'pending_provider_tasks': sum(not task.done() for task in self._orphan_tasks),
            'polls': self._polls, 'claimed': self._claimed, 'succeeded': self._succeeded,
            'partial': self._partial, 'failed': self._failed, 'fenced': self._fenced,
            'last_error': self._last_error, 'poll_interval_seconds': self._poll_interval_seconds,
        }

    def health_snapshot(self):
        result = self.snapshot()
        result.pop('last_error', None)
        return result

    async def _claim_one(self):
        async with self._session_factory() as session:
            try:
                await recover_expired_extraction_runs(
                    session, lease_seconds=self._lease_seconds, max_attempts=self._max_attempts,
                )
                run = await claim_next_extraction_run(
                    session, worker_id=self.worker_id, max_attempts=self._max_attempts,
                    lease_seconds=self._lease_seconds,
                )
                identity = (int(run.id), int(run.attempt_count), str(run.lease_token)) if run else None
                await session.commit()
                return identity
            except BaseException:
                await session.rollback()
                raise

    async def _finish_one(self, run_id, lease_token):
        run = await process_claimed_extraction_run(
            self._session_factory, run_id=run_id, worker_id=self.worker_id, lease_token=lease_token,
            stop_event=self._stop_event, lease_seconds=self._lease_seconds, orphan_tasks=self._orphan_tasks,
        )
        return str(run.status)

    async def _record_failure(self, run_id, attempt_count, lease_token, exc):
        delay = min(3600.0, self._retry_base_seconds * (2 ** min(20, max(0, attempt_count - 1))))
        async with self._session_factory() as session:
            try:
                await mark_extraction_run_failed(
                    session, run_id=run_id, worker_id=self.worker_id, lease_token=lease_token,
                    error=exc, retry_delay_seconds=delay,
                )
                await session.commit()
            except BaseException:
                await session.rollback()
                raise

    async def _release_one(self, run_id, lease_token):
        async with self._session_factory() as session:
            try:
                await release_extraction_run(session, run_id=run_id, lease_token=lease_token)
                await session.commit()
            except BaseException:
                await session.rollback()
                raise

    async def run_once(self):
        async with self._pass_lock:
            return await self._run_batch()

    async def _run_batch(self):
        totals = {'claimed': 0, 'succeeded': 0, 'partial': 0, 'failed': 0}
        for _ in range(self._batch_size):
            if self._stop_event.is_set() or any(not task.done() for task in self._orphan_tasks):
                break
            claimed = await self._claim_one()
            if claimed is None:
                break
            run_id, attempts, token = claimed
            totals['claimed'] += 1
            try:
                status = await self._finish_one(run_id, token)
                if status in ('succeeded', 'partial'):
                    totals[status] += 1
            except asyncio.CancelledError:
                await self._release_one(run_id, token)
                if not self._stop_event.is_set():
                    raise
                break
            except ExtractionLeaseLost:
                # A cancelled/reclaimed/replaced run is not ours to fail or finish.
                self._fenced += 1
            except Exception as exc:
                totals['failed'] += 1
                self._last_error = safe_exception_summary(exc)
                await self._record_failure(run_id, attempts, token, exc)
                logger.warning('knowledge extraction failed run_id=%s error=%s', run_id, self._last_error)
        self._polls += 1
        self._claimed += totals['claimed']
        self._succeeded += totals['succeeded']
        self._partial += totals['partial']
        self._failed += totals['failed']
        if not totals['failed']:
            self._last_error = None
        return totals

    def start(self):
        if self._task is not None and not self._task.done():
            return
        self._stop_event.clear()
        self._running = True
        self._task = asyncio.create_task(self._run(), name=f'knowledge-extraction:{self.worker_id}')

    async def stop(self):
        self._stop_event.set()
        task = self._task
        if task is not None and task is not asyncio.current_task():
            done, _ = await asyncio.wait({task}, timeout=self._shutdown_grace)
            if task not in done:
                task.cancel()
                # Keep the handle: start() must not admit a second loop while the
                # first is cleaning up. Lease expiry is the crash-recovery fence.
                task.add_done_callback(lambda done: None if done.cancelled() else done.exception())
            else:
                self._task = None
        self._running = False

    async def _run(self):
        try:
            while not self._stop_event.is_set():
                try:
                    await self.run_once()
                except Exception as exc:
                    self._last_error = safe_exception_summary(exc)
                    logger.warning('knowledge extraction poll failed: %s', self._last_error)
                try:
                    await asyncio.wait_for(self._stop_event.wait(), timeout=self._poll_interval_seconds)
                except asyncio.TimeoutError:
                    pass
        finally:
            self._running = False
