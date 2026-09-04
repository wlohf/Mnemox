"""Low-frequency, opt-in AgentRuntime worker.

This is intentionally smaller than a general task scheduler.  It runs one
well-defined scenario (review debt), uses the existing Coach policy as its
governor, and persists a bounded per-user schedule and replayable result.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agents.base import new_job_id
from app.models.agent import AgentExecutionLog, AgentJob
from app.models.coach import CoachPreference
from app.services.coach_runtime_service import run_proactive_review_debt_cycle
from app.services.coach_time_service import quiet_hours_end_utc
from app.utils.error_safety import safe_error_diagnostic, safe_exception_summary
from app.utils.utc import to_db_utc, to_utc_iso, utc_now_db

logger = logging.getLogger(__name__)


class AgentRuntimeWorker:
    """Lifecycle-managed scanner for opted-in proactive Coach cycles."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        poll_interval_seconds: float = 300.0,
        batch_size: int = 50,
        user_interval_seconds: int = 21600,
        retry_interval_seconds: int = 900,
        user_timeout_seconds: float = 60.0,
    ) -> None:
        if poll_interval_seconds < 30:
            raise ValueError("AgentRuntime 轮询间隔不能小于 30 秒")
        if batch_size < 1:
            raise ValueError("AgentRuntime 批量大小必须大于 0")
        if user_interval_seconds < 300:
            raise ValueError("AgentRuntime 用户评估间隔不能小于 300 秒")
        if retry_interval_seconds < 60:
            raise ValueError("AgentRuntime 失败重试间隔不能小于 60 秒")
        if user_timeout_seconds <= 0:
            raise ValueError("AgentRuntime 单用户超时必须大于 0 秒")
        self._session_factory = session_factory
        self._poll_interval_seconds = float(poll_interval_seconds)
        self._batch_size = int(batch_size)
        self._user_interval_seconds = int(user_interval_seconds)
        self._retry_interval_seconds = int(retry_interval_seconds)
        self._user_timeout_seconds = float(user_timeout_seconds)
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
        self._timed_out_users = 0
        self._quiet_hours_deferred = 0

    def snapshot(self) -> dict[str, Any]:
        diagnostic = (
            safe_error_diagnostic(
                self._last_error,
                code="agent_runtime.worker_failed",
            )
            if self._last_error
            else None
        )
        return {
            "running": self._running,
            "started_at": to_utc_iso(self._started_at) if self._started_at else None,
            "last_run_at": to_utc_iso(self._last_run_at) if self._last_run_at else None,
            "last_success_at": to_utc_iso(self._last_success_at) if self._last_success_at else None,
            "last_error_at": to_utc_iso(self._last_error_at) if self._last_error_at else None,
            "last_error": self._last_error,
            "last_error_code": diagnostic.code if diagnostic else None,
            "last_error_fingerprint": diagnostic.fingerprint if diagnostic else None,
            "cycles": self._cycles,
            "nudges_created": self._nudges_created,
            "failed_users": self._failed_users,
            "timed_out_users": self._timed_out_users,
            "quiet_hours_deferred": self._quiet_hours_deferred,
            "poll_interval_seconds": self._poll_interval_seconds,
            "user_interval_seconds": self._user_interval_seconds,
            "retry_interval_seconds": self._retry_interval_seconds,
            "user_timeout_seconds": self._user_timeout_seconds,
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
        self._started_at = utc_now_db()
        self._task = asyncio.create_task(self._run(), name="agent-runtime-worker")

    async def stop(self) -> None:
        self._stop_event.set()
        if self._task is not None and self._task is not asyncio.current_task():
            await self._task
        self._task = None
        self._running = False

    async def run_once(self, *, now: datetime | None = None) -> dict[str, int]:
        observed_now = to_db_utc(now) if now is not None else utc_now_db()
        observed_now = observed_now.replace(microsecond=0)
        self._last_run_at = observed_now
        async with self._session_factory() as session:
            result = await session.execute(
                select(CoachPreference.user_id)
                .where(
                    CoachPreference.enabled.is_(True),
                    CoachPreference.proactive_enabled.is_(True),
                    or_(
                        CoachPreference.proactive_next_evaluate_at.is_(None),
                        CoachPreference.proactive_next_evaluate_at <= observed_now,
                    ),
                )
                .order_by(
                    CoachPreference.proactive_next_evaluate_at.is_not(None),
                    CoachPreference.proactive_next_evaluate_at,
                    CoachPreference.user_id,
                )
                .limit(self._batch_size)
            )
            user_ids = [int(value) for value in result.scalars().all()]

        totals = {"scanned": 0, "nudges_created": 0, "failed": 0}
        for user_id in user_ids:
            try:
                outcome = await asyncio.wait_for(
                    self._run_user(user_id, observed_now),
                    timeout=self._user_timeout_seconds,
                )
                if outcome.get("quiet_hours_deferred"):
                    self._quiet_hours_deferred += 1
                    continue
                if not outcome["claimed"]:
                    continue
                totals["scanned"] += 1
                totals["nudges_created"] += int(outcome["nudge_created"])
            except asyncio.TimeoutError:
                totals["scanned"] += 1
                totals["failed"] += 1
                self._timed_out_users += 1
                await self._record_failure_log(user_id, observed_now)
                logger.warning(
                    "AgentRuntime cycle timed out user_id=%s timeout_seconds=%s",
                    user_id,
                    self._user_timeout_seconds,
                )
            except Exception as exc:
                totals["scanned"] += 1
                totals["failed"] += 1
                await self._record_failure_log(user_id, observed_now)
                logger.warning(
                    "AgentRuntime cycle failed user_id=%s err=%s",
                    user_id,
                    safe_exception_summary(exc),
                )

        self._cycles += 1
        self._nudges_created += totals["nudges_created"]
        self._failed_users += totals["failed"]
        if totals["failed"]:
            self._last_error_at = utc_now_db()
            self._last_error = "one or more proactive cycles failed"
        else:
            self._last_success_at = utc_now_db()
            self._last_error = None
        return totals

    async def _run_user(self, user_id: int, now: datetime) -> dict[str, Any]:
        """Claim and evaluate one user under the preference-row lock."""

        async with self._session_factory() as session:
            preference = await session.scalar(
                select(CoachPreference)
                .where(CoachPreference.user_id == user_id)
                .with_for_update(skip_locked=True)
            )
            if preference is None or not preference.enabled or not preference.proactive_enabled:
                return {"claimed": False, "nudge_created": False}
            if preference.proactive_next_evaluate_at and preference.proactive_next_evaluate_at > now:
                return {"claimed": False, "nudge_created": False}

            quiet_until = quiet_hours_end_utc(
                now,
                time_zone=preference.time_zone,
                start=preference.quiet_hours_start,
                end=preference.quiet_hours_end,
            )
            if quiet_until is not None:
                preference.proactive_next_evaluate_at = quiet_until
                await session.commit()
                return {
                    "claimed": False,
                    "nudge_created": False,
                    "quiet_hours_deferred": True,
                    "quiet_until": quiet_until,
                }

            utc_timestamp = int(now.replace(tzinfo=timezone.utc).timestamp())
            bucket = utc_timestamp // self._user_interval_seconds
            job_id = new_job_id()
            job = AgentJob(
                id=job_id,
                user_id=user_id,
                agent="runtime",
                task="review_debt_rescue",
                status="running",
                scenario="review_debt_rescue_v1",
                run_key=f"review-debt:{bucket}",
                attempt_count=int(preference.proactive_failure_count or 0) + 1,
                scheduled_for=now,
                started_at=now,
                payload={"automatic_write": False},
            )
            session.add(job)
            await session.flush()

            cycle = await run_proactive_review_debt_cycle(session, user_id, now=now)
            nudge = cycle.get("nudge") if isinstance(cycle, dict) else None
            created = isinstance(nudge, dict)
            reason = str(cycle.get("reason") or "unknown")
            job.status = "completed" if created else "skipped"
            job.finished_at = now
            job.summary = (
                "已准备一条可确认的复习积压建议"
                if created
                else f"本轮未生成建议：{reason}"
            )
            job.result = {
                "scenario": "review_debt_rescue_v1",
                "due_review_count": cycle.get("due_review_count"),
                "nudge_id": nudge.get("id") if created else None,
                "skill_id": nudge.get("skill_id") if created else None,
                "policy_reason": reason,
                "automatic_write": False,
            }
            preference.proactive_last_evaluated_at = now
            preference.proactive_next_evaluate_at = now + timedelta(seconds=self._user_interval_seconds)
            preference.proactive_failure_count = 0
            if created:
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
            await session.commit()
            return {"claimed": True, "nudge_created": created}

    async def _record_failure_log(self, user_id: int, now: datetime) -> None:
        """Keep a bounded, user-visible retry notice without leaking errors.

        The next normal low-frequency scan is the retry mechanism for this
        one read-only scenario.  Actual exception text stays in server logs;
        the user only sees that no action was taken and nothing was changed.
        """

        try:
            async with self._session_factory() as session:
                preference = await session.scalar(
                    select(CoachPreference)
                    .where(CoachPreference.user_id == user_id)
                    .with_for_update()
                )
                failure_count = int(preference.proactive_failure_count or 0) + 1 if preference else 1
                retry_seconds = min(
                    self._user_interval_seconds,
                    self._retry_interval_seconds * (2 ** min(failure_count - 1, 5)),
                )
                if preference is not None:
                    preference.proactive_last_evaluated_at = now
                    preference.proactive_next_evaluate_at = now + timedelta(seconds=retry_seconds)
                    preference.proactive_failure_count = failure_count
                job_id = new_job_id()
                session.add(
                    AgentJob(
                        id=job_id,
                        user_id=user_id,
                        agent="runtime",
                        task="review_debt_rescue",
                        status="failed",
                        scenario="review_debt_rescue_v1",
                        run_key=(
                            "review-debt-failure:"
                            f"{int(now.replace(tzinfo=timezone.utc).timestamp())}:{job_id}"
                        ),
                        attempt_count=failure_count,
                        scheduled_for=now,
                        started_at=now,
                        finished_at=now,
                        payload={"automatic_write": False},
                        result={"retry_in_seconds": retry_seconds, "automatic_write": False},
                        summary="后台评估暂未完成，已安排安全重试",
                    )
                )
                session.add(
                    AgentExecutionLog(
                        id=new_job_id(),
                        user_id=user_id,
                        job_id=job_id,
                        agent="runtime",
                        status="retrying",
                        message="后台评估暂未完成，稍后会再次检查；没有修改你的计划或任务。",
                        extra_metadata={
                            "scenario": "review_debt_rescue_v1",
                            "automatic_write": False,
                            "retry": "scheduled",
                            "retry_in_seconds": retry_seconds,
                        },
                    )
                )
                await session.commit()
        except Exception as log_error:
            logger.warning(
                "AgentRuntime failure log could not be persisted user_id=%s err=%s",
                user_id,
                safe_exception_summary(log_error),
            )

    async def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                await self.run_once()
            except Exception as exc:
                self._last_error_at = utc_now_db()
                self._last_error = "worker cycle failed"
                logger.warning("AgentRuntime worker cycle failed: %s", safe_exception_summary(exc))
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=self._poll_interval_seconds)
            except asyncio.TimeoutError:
                continue
