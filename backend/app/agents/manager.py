"""Agent runtime manager with database-backed jobs and logs."""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import AgentRunContext, new_job_id, utc_now_iso
from app.agents.chat_agent import ChatAgent
from app.agents.review_agent import ReviewAgent
from app.agents.study_plan_agent import StudyPlanAgent
from app.models.agent import AgentExecutionLog, AgentJob
from app.utils.error_safety import (
    redact_sensitive_text,
    safe_error_diagnostic,
    safe_exception_diagnostic,
)
from app.utils.utc import to_utc_iso, utc_now_db


class AgentManager:
    def __init__(self) -> None:
        self.agents = {
            StudyPlanAgent.name: StudyPlanAgent(),
            ReviewAgent.name: ReviewAgent(),
            ChatAgent.name: ChatAgent(),
        }

    def list_agents(self) -> list[dict[str, str]]:
        return [
            {"name": a.name, "display_name": a.display_name, "description": a.description}
            for a in self.agents.values()
        ]

    async def status(self, db: AsyncSession, user_id: int) -> dict[str, Any]:
        jobs = await self._recent_jobs(db, user_id)
        logs = await self._recent_logs(db, user_id)
        return {
            "status": (
                "running"
                if any(j.get("status") in {"pending", "running", "cancelling"} for j in jobs)
                else "idle"
            ),
            "agents": self.list_agents(),
            "task_queue": jobs,
            "execution_logs": logs,
        }

    async def trigger(
        self,
        db: AsyncSession,
        user_id: int,
        agent_name: str,
        task: str = "run",
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if agent_name not in self.agents:
            raise ValueError("未知 Agent")

        job = AgentJob(
            id=new_job_id(),
            user_id=user_id,
            agent=agent_name,
            task=task or "run",
            status="running",
            payload=payload or {},
        )
        db.add(job)
        await db.flush()
        await self._log(db, user_id, agent_name, "started", f"开始执行 {agent_name}.{task or 'run'}", job.id)
        await db.flush()

        try:
            result = await self.agents[agent_name].run(
                AgentRunContext(db=db, user_id=user_id, task=task or "run", payload=payload or {})
            )
            safe_summary = redact_sensitive_text(result.summary, max_chars=2000, fallback="")
            stored_result = asdict(result)
            stored_result["summary"] = safe_summary
            job.status = result.status
            job.summary = safe_summary
            job.result = stored_result
            job.updated_at = utc_now_db()
            await self._log(db, user_id, agent_name, result.status, safe_summary, job.id)
            await db.commit()
            return {
                "job": self._job_to_dict(job),
                "result": stored_result,
                "runtime": await self.status(db, user_id),
            }
        except Exception as exc:
            await db.rollback()
            diagnostic = safe_exception_diagnostic(
                exc,
                code="agent.execution_failed",
                max_chars=2000,
            )
            safe_error = diagnostic.summary
            job = AgentJob(
                id=job.id,
                user_id=user_id,
                agent=agent_name,
                task=task or "run",
                status="failed",
                payload=payload or {},
                summary=safe_error,
                result=diagnostic.as_dict(),
                updated_at=utc_now_db(),
            )
            db.add(job)
            await self._log(db, user_id, agent_name, "failed", safe_error, job.id)
            await db.commit()
            raise

    async def call_chat_tool(self, db: AsyncSession, user_id: int, tool: str, query: str, limit: int = 5) -> dict[str, Any]:
        """Run one read-only tool without committing the caller's unit of work."""
        agent = self.agents[ChatAgent.name]
        ctx = AgentRunContext(db=db, user_id=user_id, task=tool, payload={"tool": tool, "query": query, "limit": limit})
        data = await agent.call_tool(ctx, tool=tool, query=query, limit=limit)
        await self._log(db, user_id, ChatAgent.name, "completed", f"调用工具 {tool}，返回 {len(data.get('items', []))} 条", None)
        await db.flush()
        return data

    async def _recent_jobs(self, db: AsyncSession, user_id: int, limit: int = 30) -> list[dict[str, Any]]:
        result = await db.execute(
            select(AgentJob)
            .where(AgentJob.user_id == user_id)
            .order_by(AgentJob.created_at.desc(), AgentJob.id.desc())
            .limit(limit)
        )
        return [self._job_to_dict(job) for job in result.scalars().all()]

    async def _recent_logs(self, db: AsyncSession, user_id: int, limit: int = 100) -> list[dict[str, Any]]:
        result = await db.execute(
            select(AgentExecutionLog)
            .where(AgentExecutionLog.user_id == user_id)
            .order_by(AgentExecutionLog.created_at.desc(), AgentExecutionLog.id.desc())
            .limit(limit)
        )
        return [self._log_to_dict(log) for log in result.scalars().all()]

    async def _log(
        self,
        db: AsyncSession,
        user_id: int,
        agent: str,
        status: str,
        message: str,
        job_id: str | None,
    ) -> None:
        db.add(
            AgentExecutionLog(
                id=new_job_id(),
                user_id=user_id,
                job_id=job_id,
                agent=agent,
                status=status,
                message=redact_sensitive_text(message, max_chars=2000, fallback=""),
            )
        )

    def _job_to_dict(self, job: AgentJob) -> dict[str, Any]:
        checkpoint_step: int | None = None
        checkpoint_recoverable = False
        if (
            isinstance(job.checkpoint, dict)
            and job.checkpoint.get("version") == 1
            and isinstance(job.checkpoint.get("messages"), list)
            and bool(job.checkpoint.get("messages"))
        ):
            try:
                checkpoint_step = max(0, int(job.checkpoint.get("next_step_index") or 1) - 1)
                checkpoint_recoverable = True
            except (TypeError, ValueError):
                checkpoint_step = None
        error_code: str | None = None
        error_fingerprint: str | None = None
        if job.status == "failed":
            diagnostic = safe_error_diagnostic(
                job.summary or "agent execution failed",
                code="agent.execution_failed",
                max_chars=2000,
            )
            error_code = diagnostic.code
            error_fingerprint = diagnostic.fingerprint

        return {
            "id": job.id,
            "agent": job.agent,
            "task": job.task,
            "status": job.status,
            "scenario": job.scenario,
            "run_key": job.run_key,
            "attempt_count": int(job.attempt_count or 0),
            "scheduled_for": self._dt_to_iso(job.scheduled_for) if job.scheduled_for else None,
            "started_at": self._dt_to_iso(job.started_at) if job.started_at else None,
            "finished_at": self._dt_to_iso(job.finished_at) if job.finished_at else None,
            "cancel_requested_at": (
                self._dt_to_iso(job.cancel_requested_at) if job.cancel_requested_at else None
            ),
            "resumed_from_job_id": job.resumed_from_job_id,
            "lease_expires_at": (
                self._dt_to_iso(job.lease_expires_at) if job.lease_expires_at else None
            ),
            "recoverable": bool(
                job.status in {"failed", "cancelled"}
                and checkpoint_recoverable
            ),
            "checkpoint_step": checkpoint_step,
            "payload": job.payload or {},
            "summary": (
                redact_sensitive_text(job.summary, max_chars=2000, fallback="")
                if job.summary
                else job.summary
            ),
            "error_code": error_code,
            "error_fingerprint": error_fingerprint,
            "result": job.result,
            "created_at": self._dt_to_iso(job.created_at),
            "updated_at": self._dt_to_iso(job.updated_at),
        }

    def _log_to_dict(self, log: AgentExecutionLog) -> dict[str, Any]:
        return {
            "id": log.id,
            "job_id": log.job_id,
            "agent": log.agent,
            "status": log.status,
            "message": redact_sensitive_text(log.message, max_chars=2000, fallback=""),
            "metadata": log.extra_metadata or {},
            "created_at": self._dt_to_iso(log.created_at),
        }

    def _dt_to_iso(self, value: datetime | None) -> str:
        if not value:
            return utc_now_iso()
        return to_utc_iso(value)


agent_manager = AgentManager()
