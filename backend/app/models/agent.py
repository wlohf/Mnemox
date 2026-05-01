"""Agent runtime 持久化模型。"""
from sqlalchemy import Column, DateTime, Integer, JSON, String, Text
from sqlalchemy.sql import func

from app.database import Base


class AgentJob(Base):
    """Agent 任务记录。"""

    __tablename__ = "agent_jobs"

    id = Column(String(32), primary_key=True)
    user_id = Column(Integer, nullable=False, index=True)
    agent = Column(String(50), nullable=False, index=True)
    task = Column(String(100), nullable=False, default="run")
    status = Column(String(20), nullable=False, default="pending", index=True)
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
