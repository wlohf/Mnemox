"""Recover interrupted AgentKernel runs without racing a live owner."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agents.base import new_job_id
from app.models.agent import AgentExecutionLog, AgentJob
from app.utils.error_safety import safe_exception_summary
from app.utils.utc import to_db_utc, to_utc_iso, utc_now_db

logger = logging.getLogger(__name__)


def _checkpoint_step(checkpoint: Any) -> int | None:
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


async def recover_expired_agent_kernel_jobs(
    db: AsyncSession,
    *,
    now: datetime | None = None,
) -> int:
    """Terminalize only active Kernel jobs whose lease has expired.

    PostgreSQL locks candidate rows with ``SKIP LOCKED`` so concurrent app
    startups cannot recover the same run. Jobs created before leases existed
    have a NULL expiry and are deliberately left untouched during rolling
    deployments.
    """

    recovered_at = (
        to_db_utc(now) if now is not None else utc_now_db()
    ).replace(microsecond=0)
    result = await db.execute(
        select(AgentJob)
        .where(
            AgentJob.agent == "kernel",
            AgentJob.scenario == "agent_kernel_v1",
            AgentJob.status.in_(("running", "cancelling")),
            AgentJob.lease_expires_at.is_not(None),
            AgentJob.lease_expires_at <= recovered_at,
        )
        .order_by(AgentJob.lease_expires_at, AgentJob.id)
        .with_for_update(skip_locked=True)
    )
    jobs = list(result.scalars().all())

    for job in jobs:
        prior_status = str(job.status)
        stored = dict(job.result) if isinstance(job.result, dict) else {}
        steps = stored.get("steps") if isinstance(stored.get("steps"), list) else []
        checkpoint_usage = (
            job.checkpoint.get("usage")
            if isinstance(job.checkpoint, dict) and isinstance(job.checkpoint.get("usage"), dict)
            else stored.get("usage") if isinstance(stored.get("usage"), dict) else {}
        )
        checkpoint_step = _checkpoint_step(job.checkpoint)
        cancelled = bool(job.cancel_requested_at or prior_status == "cancelling")

        job.status = "cancelled" if cancelled else "failed"
        job.finished_at = recovered_at
        job.lease_owner = None
        job.lease_expires_at = None
        job.updated_at = recovered_at
        if cancelled:
            job.summary = "AgentKernel 在进程恢复时确认取消"
            job.result = {
                "status": "cancelled",
                "reason": "cancelled_by_user",
                "steps": steps,
                "recoverable": checkpoint_step is not None,
                "checkpoint_step": checkpoint_step,
                "usage": checkpoint_usage,
            }
            log_status = "cancelled"
            log_message = "进程恢复时确认了用户取消；没有执行任何写入"
        else:
            job.summary = (
                f"AgentKernel 进程中断，可从 step {checkpoint_step} 继续"
                if checkpoint_step is not None
                else "AgentKernel 进程中断，可沿用原目标重新运行"
            )
            job.result = {
                "status": "failed",
                "error": "process_interrupted",
                "steps": steps,
                "recoverable": checkpoint_step is not None,
                "checkpoint_step": checkpoint_step,
                "usage": checkpoint_usage,
            }
            log_status = "interrupted"
            log_message = (
                "运行租约已过期；任务已安全停止，可从持久 checkpoint 继续"
                if checkpoint_step is not None
                else "运行租约已过期；任务已安全停止，可沿用原目标重新运行"
            )

        db.add(
            AgentExecutionLog(
                id=new_job_id(),
                user_id=int(job.user_id),
                job_id=str(job.id),
                agent="kernel",
                status=log_status,
                message=log_message,
                extra_metadata={
                    "reason": "process_interrupted",
                    "previous_status": prior_status,
                    "checkpoint_step": checkpoint_step,
                },
                created_at=recovered_at,
            )
        )

    if jobs:
        await db.flush()
    return len(jobs)


class AgentJobRecoveryWorker:
    """Small lifecycle task that eventually reaps leases expiring after boot."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        poll_interval_seconds: float = 30.0,
    ) -> None:
        if poll_interval_seconds < 1:
            raise ValueError("AgentKernel 回收轮询间隔不能小于 1 秒")
        self._session_factory = session_factory
        self._poll_interval_seconds = float(poll_interval_seconds)
        self._stop_event = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._running = False
        self._last_run_at: datetime | None = None
        self._recovered_jobs = 0

    def snapshot(self) -> dict[str, Any]:
        return {
            "running": self._running,
            "poll_interval_seconds": self._poll_interval_seconds,
            "last_run_at": to_utc_iso(self._last_run_at) if self._last_run_at else None,
            "recovered_jobs": self._recovered_jobs,
        }

    def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._stop_event.clear()
        self._running = True
        self._task = asyncio.create_task(self._run(), name="agent-job-recovery-worker")

    async def stop(self) -> None:
        self._stop_event.set()
        if self._task is not None and self._task is not asyncio.current_task():
            await self._task
        self._task = None
        self._running = False

    async def run_once(self) -> int:
        self._last_run_at = utc_now_db().replace(microsecond=0)
        async with self._session_factory() as session:
            recovered = await recover_expired_agent_kernel_jobs(session, now=self._last_run_at)
            if recovered:
                await session.commit()
                self._recovered_jobs += recovered
            return recovered

    async def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                recovered = await self.run_once()
                if recovered:
                    logger.warning("recovered %d expired AgentKernel jobs", recovered)
            except Exception as exc:
                logger.warning("AgentKernel recovery cycle failed: %s", safe_exception_summary(exc))
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(), timeout=self._poll_interval_seconds
                )
            except asyncio.TimeoutError:
                continue
