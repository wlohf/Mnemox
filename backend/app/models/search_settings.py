"""Persistent web search settings."""
from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.sql import func

from app.database import Base


class AISearchSettings(Base):
    """Per-user search provider configuration."""

    __tablename__ = "ai_search_settings"

    user_id = Column(Integer, ForeignKey("users.id"), primary_key=True, nullable=False)
    enabled = Column(Boolean, nullable=False, default=False)
    default_mode = Column(String(40), nullable=False, default="auto")
    provider = Column(String(40), nullable=False, default="auto")
    tavily_api_key = Column(Text, nullable=False, default="")
    tavily_search_depth = Column(String(20), nullable=False, default="advanced")
    tavily_max_results = Column(Integer, nullable=False, default=8)
    tavily_chunks_per_source = Column(Integer, nullable=False, default=3)
    tavily_include_answer = Column(Boolean, nullable=False, default=False)
    tavily_include_raw_content = Column(Boolean, nullable=False, default=False)
    timeout_seconds = Column(Float, nullable=False, default=12.0)
    fallback_enabled = Column(Boolean, nullable=False, default=True)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
