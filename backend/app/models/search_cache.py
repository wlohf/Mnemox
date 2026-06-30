"""Persistent cache for normalized web search results."""
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.sql import func

from app.database import Base


class WebSearchCache(Base):
    """Per-user cache for app-layer web search results."""

    __tablename__ = "web_search_cache"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    query_hash = Column(String(64), nullable=False, index=True)
    normalized_query = Column(Text, nullable=False)
    mode = Column(String(40), nullable=False, default="auto")
    provider = Column(String(40), nullable=False, default="auto")
    quality_key = Column(String(300), nullable=False, default="")
    results_json = Column(Text, nullable=False, default="[]")
    summary = Column(Text, nullable=True)
    source_count = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    expires_at = Column(DateTime, nullable=False, index=True)
