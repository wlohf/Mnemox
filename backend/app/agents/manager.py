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
            "status": "running" if any(j.get("status") == "running" for j in jobs) else "idle",
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
            job.status = result.status
            job.summary = result.summary
            job.result = asdict(result)
            job.updated_at = datetime.utcnow()
            await self._log(db, user_id, agent_name, result.status, result.summary, job.id)
            await db.commit()
            return {
                "job": self._job_to_dict(job),
                "result": asdict(result),
                "runtime": await self.status(db, user_id),
            }
        except Exception as exc:
            await db.rollback()
            job = AgentJob(
                id=job.id,
                user_id=user_id,
                agent=agent_name,
                task=task or "run",
                status="failed",
                payload=payload or {},
                summary=str(exc),
                updated_at=datetime.utcnow(),
            )
            db.add(job)
            await self._log(db, user_id, agent_name, "failed", str(exc), job.id)
            await db.commit()
            raise

    async def call_chat_tool(self, db: AsyncSession, user_id: int, tool: str, query: str, limit: int = 5) -> dict[str, Any]:
        agent = self.agents[ChatAgent.name]
        ctx = AgentRunContext(db=db, user_id=user_id, task=tool, payload={"tool": tool, "query": query, "limit": limit})
        data = await agent.call_tool(ctx, tool=tool, query=query, limit=limit)
        await self._log(db, user_id, ChatAgent.name, "completed", f"调用工具 {tool}，返回 {len(data.get('items', []))} 条", None)
        await db.commit()
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
                message=message,
            )
        )

    def _job_to_dict(self, job: AgentJob) -> dict[str, Any]:
        return {
            "id": job.id,
            "agent": job.agent,
            "task": job.task,
            "status": job.status,
            "payload": job.payload or {},
            "summary": job.summary,
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
            "message": log.message,
            "metadata": log.extra_metadata or {},
            "created_at": self._dt_to_iso(log.created_at),
        }

    def _dt_to_iso(self, value: datetime | None) -> str:
        if not value:
            return utc_now_iso()
        return value.isoformat() + ("Z" if value.tzinfo is None else "")


agent_manager = AgentManager()
