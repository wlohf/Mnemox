"""Durable request receipts for offline synchronization mutations."""
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.sql import func

from app.database import Base


class SyncReceipt(Base):
    """One immutable idempotency result per user and client operation key."""

    __tablename__ = "sync_receipts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    idempotency_key = Column(String(36), nullable=False)
    method = Column(String(10), nullable=False)
    path = Column(String(500), nullable=False)
    fingerprint = Column(String(64), nullable=False)
    status_code = Column(Integer, nullable=True)
    response_body = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("user_id", "idempotency_key", name="uq_sync_receipts_user_key"),
    )
