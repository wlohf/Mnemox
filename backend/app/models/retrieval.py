"""Durable, rebuildable retrieval projections and their SQL chunk manifests."""
from __future__ import annotations

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class RetrievalProjection(Base):
    """User-scoped lifecycle state for a derived retrieval backend.

    ``source_id`` intentionally has no material foreign key: a failed forget must
    remain recoverable after its canonical source has already been deleted.
    The owning user still cascades, and source visibility is always checked
    against canonical SQL before a retrieval result is returned.
    """

    __tablename__ = "retrieval_projections"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "source_type",
            "source_id",
            "backend",
            name="uq_retrieval_projection_source_backend",
        ),
        CheckConstraint(
            "status IN ('pending', 'indexing', 'ready', 'degraded', 'failed', 'deleting', 'deleted')",
            name="ck_retrieval_projection_status",
        ),
        CheckConstraint("source_version >= 1", name="ck_retrieval_projection_source_version"),
        CheckConstraint("attempt_count >= 0", name="ck_retrieval_projection_attempt_count"),
        CheckConstraint("chunk_count >= 0", name="ck_retrieval_projection_chunk_count"),
        CheckConstraint(
            "vector_chunk_count >= 0", name="ck_retrieval_projection_vector_chunk_count"
        ),
        Index("ix_retrieval_projections_user_status", "user_id", "status", "updated_at"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    source_type = Column(String(30), nullable=False, default="material", server_default="material")
    source_id = Column(Integer, nullable=False)
    backend = Column(String(30), nullable=False, default="chroma", server_default="chroma")
    status = Column(String(20), nullable=False, default="pending", server_default="pending")
    last_operation = Column(String(20), nullable=False, default="ingest", server_default="ingest")
    source_version = Column(Integer, nullable=False, default=1, server_default="1")
    indexed_version = Column(Integer, nullable=True)
    source_signature = Column(String(64), nullable=True)
    content_hash = Column(String(64), nullable=True)
    configuration_fingerprint = Column(String(64), nullable=True)
    embedding_model = Column(String(160), nullable=True)
    chunk_size = Column(Integer, nullable=True)
    chunk_overlap = Column(Integer, nullable=True)
    chunk_count = Column(Integer, nullable=False, default=0, server_default="0")
    vector_chunk_count = Column(Integer, nullable=False, default=0, server_default="0")
    attempt_count = Column(Integer, nullable=False, default=0, server_default="0")
    last_error = Column(Text, nullable=True)
    last_indexed_at = Column(DateTime, nullable=True)
    deleted_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())

    chunks = relationship(
        "RetrievalProjectionChunk",
        back_populates="projection",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class RetrievalProjectionChunk(Base):
    """Rebuildable SQL sparse manifest; canonical text remains ``Material.content``."""

    __tablename__ = "retrieval_projection_chunks"
    __table_args__ = (
        UniqueConstraint("projection_id", "chunk_index", name="uq_retrieval_projection_chunk"),
        CheckConstraint("chunk_index >= 0", name="ck_retrieval_projection_chunk_index"),
        CheckConstraint("source_version >= 1", name="ck_retrieval_chunk_source_version"),
        Index("ix_retrieval_projection_chunks_user_source", "user_id", "source_type", "source_id"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    projection_id = Column(
        Integer,
        ForeignKey("retrieval_projections.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    source_type = Column(String(30), nullable=False, default="material", server_default="material")
    source_id = Column(Integer, nullable=False)
    source_version = Column(Integer, nullable=False, default=1, server_default="1")
    chunk_index = Column(Integer, nullable=False)
    chunk_hash = Column(String(64), nullable=False)
    text = Column(Text, nullable=False)
    created_at = Column(DateTime, nullable=False, server_default=func.now())

    projection = relationship("RetrievalProjection", back_populates="chunks")
