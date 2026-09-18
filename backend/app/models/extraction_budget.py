"""Durable, source-free accounting for LLM extraction calls."""
from __future__ import annotations

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.sql import func

from app.database import Base


class ExtractionDailyBudget(Base):
    """One user's conservatively charged extraction-token total for a UTC day."""

    __tablename__ = "knowledge_extraction_daily_budgets"
    __table_args__ = (
        UniqueConstraint("user_id", "execution_day", name="uq_extraction_daily_budget_user_day"),
        CheckConstraint("charged_tokens >= 0", name="ck_extraction_daily_budget_charged_tokens"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    execution_day = Column(Date, nullable=False)
    charged_tokens = Column(Integer, nullable=False, default=0, server_default="0")
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())


class ExtractionCall(Base):
    """An idempotent LLM attempt ledger row; never stores source or model payloads."""

    __tablename__ = "knowledge_extraction_calls"
    __table_args__ = (
        CheckConstraint("estimated_tokens > 0", name="ck_extraction_call_estimated_tokens"),
        CheckConstraint("charged_tokens >= estimated_tokens", name="ck_extraction_call_charged_tokens"),
        CheckConstraint(
            "state IN ('reserved', 'succeeded', 'failed', 'unknown')",
            name="ck_extraction_call_state",
        ),
        Index("ix_extraction_calls_run", "run_id"),
        Index("ix_extraction_calls_user_day", "user_id", "execution_day"),
    )

    id = Column(String(36), primary_key=True)
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    run_id = Column(
        Integer,
        ForeignKey("knowledge_extraction_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    unit_id = Column(
        Integer,
        ForeignKey("knowledge_units.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    lease_token = Column(String(36), nullable=False)
    execution_day = Column(Date, nullable=False)
    estimated_tokens = Column(Integer, nullable=False)
    charged_tokens = Column(Integer, nullable=False)
    state = Column(String(20), nullable=False, default="reserved", server_default="reserved")
    usage = Column(JSON, nullable=False, default=dict, server_default="{}")
    provider = Column(String(80), nullable=True)
    model = Column(String(120), nullable=True)
    started_at = Column(DateTime, nullable=False, server_default=func.now())
    finished_at = Column(DateTime, nullable=True)
