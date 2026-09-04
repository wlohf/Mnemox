"""Agent runtime 持久化模型。"""
from sqlalchemy import Column, DateTime, Index, Integer, JSON, String, Text
from sqlalchemy.sql import func

from app.database import Base


class AgentJob(Base):
    """Agent 任务记录。"""

    __tablename__ = "agent_jobs"
    __table_args__ = (Index("uq_agent_jobs_user_run_key", "user_id", "run_key", unique=True),)

    id = Column(String(32), primary_key=True)
    user_id = Column(Integer, nullable=False, index=True)
    agent = Column(String(50), nullable=False, index=True)
    task = Column(String(100), nullable=False, default="run")
    status = Column(String(20), nullable=False, default="pending", index=True)
    scenario = Column(String(100), nullable=True, index=True)
    run_key = Column(String(160), nullable=True)
    attempt_count = Column(Integer, nullable=False, default=0)
    scheduled_for = Column(DateTime, nullable=True, index=True)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    cancel_requested_at = Column(DateTime, nullable=True)
    resumed_from_job_id = Column(String(32), nullable=True, index=True)
    lease_owner = Column(String(64), nullable=True)
    lease_expires_at = Column(DateTime, nullable=True, index=True)
    checkpoint = Column(JSON, nullable=True)
    payload = Column(JSON, default=dict)
    result = Column(JSON)
    summary = Column(Text)
    created_at = Column(DateTime, server_default=func.now(), index=True)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class AgentExecutionLog(Base):
    """Agent 执行日志。"""

    __tablename__ = "agent_execution_logs"

    id = Column(String(32), primary_key=True)
    user_id = Column(Integer, nullable=False, index=True)
    job_id = Column(String(32), index=True)
    agent = Column(String(50), nullable=False, index=True)
    status = Column(String(20), nullable=False)
    message = Column(Text, nullable=False)
    extra_metadata = Column("metadata", JSON)
    created_at = Column(DateTime, server_default=func.now(), index=True)


class AgentActionConfirmation(Base):
    """Durable, user-confirmed execution receipt for a persisted Agent action."""

    __tablename__ = "agent_action_confirmations"
    __table_args__ = (
        Index(
            "uq_agent_action_confirmations_user_job_action",
            "user_id",
            "job_id",
            "action_id",
            unique=True,
        ),
    )

    id = Column(String(32), primary_key=True)
    user_id = Column(Integer, nullable=False, index=True)
    job_id = Column(String(32), nullable=False, index=True)
    action_id = Column(String(64), nullable=False)
    status = Column(String(20), nullable=False, default="prepared", index=True)
    action_snapshot = Column(JSON, nullable=False)
    draft = Column(JSON, nullable=False)
    result = Column(JSON)
    confirmed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), index=True)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
