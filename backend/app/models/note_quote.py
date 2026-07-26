"""笔记自引使用记录：防疲劳冷却与采纳反馈的数据基础。"""
from __future__ import annotations

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.sql import func

from app.database import Base


class NoteQuoteUsage(Base):
    """一次"引用用户自己的笔记"的使用记录。

    - 冷却：同一 excerpt_hash 在冷却期内不再被选中（防疲劳）。
    - 反馈：nudge 收到反馈时回写 feedback_outcome，用于后续策略学习。
    """

    __tablename__ = "note_quote_usages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    note_id = Column(Integer, nullable=True, index=True, comment="被引用的笔记ID")
    excerpt_hash = Column(String(64), nullable=False, index=True, comment="摘录指纹 sha256")
    excerpt_preview = Column(String(200), nullable=True, comment="摘录预览（排查用）")
    channel = Column(String(40), nullable=False, default="coach", comment="引用渠道: coach | motivation")
    nudge_id = Column(String(40), nullable=True, index=True, comment="关联的 Coach nudge")
    feedback_outcome = Column(String(40), nullable=True, comment="nudge 反馈结果回写")
    quoted_at = Column(DateTime, server_default=func.now(), nullable=False, index=True, comment="引用时间")
