"""Low-frequency, opt-in AgentRuntime worker.

This is intentionally smaller than a general task scheduler.  It runs one
well-defined scenario (review debt), uses the existing Coach policy as its
governor, and records only meaningful nudge creation as an Agent job.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agents.base import new_job_id
from app.models.agent import AgentExecutionLog, AgentJob
from app.models.coach import CoachPreference
from app.services.coach_runtime_service import run_proactive_review_debt_cycle

logger = logging.getLogger(__name__)


class AgentRuntimeWorker:
    """Lifecycle-managed scanner for opted-in proactive Coach cycles."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        poll_interval_seconds: float = 300.0,
        batch_size: int = 50,
    ) -> None:
        if poll_interval_seconds < 30:
            raise ValueError("AgentRuntime 轮询间隔不能小于 30 秒")
        if batch_size < 1:
            raise ValueError("AgentRuntime 批量大小必须大于 0")
        self._session_factory = session_factory
        self._poll_interval_seconds = float(poll_interval_seconds)
        self._batch_size = int(batch_size)
        self._stop_event = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._running = False
        self._started_at: datetime | None = None
        self._last_run_at: datetime | None = None
        self._last_success_at: datetime | None = None
        self._last_error_at: datetime | None = None
        self._last_error: str | None = None
        self._cycles = 0
        self._nudges_created = 0
        self._failed_users = 0

    def snapshot(self) -> dict[str, Any]:
        return {
            "running": self._running,
            "started_at": self._started_at.isoformat() if self._started_at else None,
            "last_run_at": self._last_run_at.isoformat() if self._last_run_at else None,
            "last_success_at": self._last_success_at.isoformat() if self._last_success_at else None,
            "last_error_at": self._last_error_at.isoformat() if self._last_error_at else None,
            "last_error": self._last_error,
            "cycles": self._cycles,
            "nudges_created": self._nudges_created,
            "failed_users": self._failed_users,
            "poll_interval_seconds": self._poll_interval_seconds,
        }

    def health_snapshot(self) -> dict[str, Any]:
        snapshot = self.snapshot()
        snapshot.pop("last_error", None)
        return snapshot

    def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._stop_event.clear()
        self._running = True
        self._started_at = datetime.now()
        self._task = asyncio.create_task(self._run(), name="agent-runtime-worker")

    async def stop(self) -> None:
        self._stop_event.set()
        if self._task is not None and self._task is not asyncio.current_task():
            await self._task
        self._task = None
        self._running = False

    async def run_once(self) -> dict[str, int]:
        self._last_run_at = datetime.now()
        async with self._session_factory() as session:
            result = await session.execute(
                select(CoachPreference.user_id)
                .where(
                    CoachPreference.enabled.is_(True),
                    CoachPreference.proactive_enabled.is_(True),
                )
                .order_by(CoachPreference.user_id)
                .limit(self._batch_size)
            )
            user_ids = [int(value) for value in result.scalars().all()]

        totals = {"scanned": 0, "nudges_created": 0, "failed": 0}
        for user_id in user_ids:
            totals["scanned"] += 1
            try:
                async with self._session_factory() as session:
                    cycle = await run_proactive_review_debt_cycle(session, user_id)
                    nudge = cycle.get("nudge") if isinstance(cycle, dict) else None
                    if isinstance(nudge, dict):
                        job_id = new_job_id()
                        session.add(
                            AgentJob(
                                id=job_id,
                                user_id=user_id,
                                agent="runtime",
                                task="review_debt_rescue",
                                status="completed",
                                payload={
                                    "scenario": "review_debt_rescue_v1",
                                    "due_review_count": cycle.get("due_review_count"),
                                },
                                result={
                                    "nudge_id": nudge.get("id"),
                                    "skill_id": nudge.get("skill_id"),
                                    "policy_reason": cycle.get("reason"),
                                },
                                summary="已准备一条可确认的复习积压建议",
                            )
                        )
                        # Only persist a user-visible runtime record when the
                        # worker produced something meaningful.  Routine scans
                        # and policy-blocked checks stay silent so the Agent
                        # history does not become a five-minute audit flood.
                        session.add(
                            AgentExecutionLog(
                                id=new_job_id(),
                                user_id=user_id,
                                job_id=job_id,
                                agent="runtime",
                                status="completed",
                                message="后台评估已生成一条可自行决定是否执行的复习建议",
                                extra_metadata={
                                    "scenario": "review_debt_rescue_v1",
                                    "due_review_count": cycle.get("due_review_count"),
                                    "automatic_write": False,
                                },
                            )
                        )
                        totals["nudges_created"] += 1
                    await session.commit()
            except Exception as exc:
                totals["failed"] += 1
                await self._record_failure_log(user_id)
                logger.warning("AgentRuntime cycle failed user_id=%s err=%s", user_id, exc, exc_info=True)

        self._cycles += 1
        self._nudges_created += totals["nudges_created"]
        self._failed_users += totals["failed"]
        if totals["failed"]:
            self._last_error_at = datetime.now()
            self._last_error = "one or more proactive cycles failed"
        else:
            self._last_success_at = datetime.now()
            self._last_error = None
        return totals

    async def _record_failure_log(self, user_id: int) -> None:
        """Keep a bounded, user-visible retry notice without leaking errors.

        The next normal low-frequency scan is the retry mechanism for this
        one read-only scenario.  Actual exception text stays in server logs;
        the user only sees that no action was taken and nothing was changed.
        """

        try:
            async with self._session_factory() as session:
                session.add(
                    AgentExecutionLog(
                        id=new_job_id(),
                        user_id=user_id,
                        job_id=None,
                        agent="runtime",
                        status="retrying",
                        message="后台评估暂未完成，稍后会再次检查；没有修改你的计划或任务。",
                        extra_metadata={
                            "scenario": "review_debt_rescue_v1",
                            "automatic_write": False,
                            "retry": "next_poll",
                        },
                    )
                )
                await session.commit()
        except Exception as log_error:
            logger.warning("AgentRuntime failure log could not be persisted user_id=%s err=%s", user_id, log_error)

    async def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                await self.run_once()
            except Exception as exc:
                self._last_error_at = datetime.now()
                self._last_error = "worker cycle failed"
                logger.warning("AgentRuntime worker cycle failed: %s", exc, exc_info=True)
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=self._poll_interval_seconds)
            except asyncio.TimeoutError:
                continue
