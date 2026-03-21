"""AI 记忆模型：会话摘要 + 长期记忆"""
from sqlalchemy import Column, Integer, String, Text, DateTime, Float, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class ConversationSummary(Base):
    """对话级摘要（可滚动更新）"""
    __tablename__ = "conversation_summaries"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, default=1, index=True, comment="所属用户")
    conversation_id = Column(Integer, ForeignKey("chat_conversations.id", ondelete="CASCADE"), nullable=False, index=True)
    summary = Column(Text, comment="会话摘要")
    key_points = Column(Text, comment="JSON 列表，关键点")
    todo_items = Column(Text, comment="JSON 列表，后续待办")
    message_count = Column(Integer, default=0, comment="摘要时的消息数")
    last_message_at = Column(DateTime, comment="摘要时最后一条消息时间")
    created_at = Column(DateTime, server_default=func.now(), comment="创建时间")
    questions_asked = Column(Text, comment="JSON: 用户提出的关键问题")
    confusions = Column(Text, comment="JSON: 用户表现出的困惑点")
    misconceptions = Column(Text, comment="JSON: 用户暴露的错误理解")
    review_prompts = Column(Text, comment="JSON: AI建议的复习提示语")
    reflection_turn_count = Column(Integer, default=0, comment="已做反思时的消息轮数")
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), comment="更新时间")


class UserMemory(Base):
    """长期记忆条目（结构化事实）"""
    __tablename__ = "user_memories"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, default=1, index=True, comment="所属用户")
    memory_key = Column(String(100), nullable=False, index=True, comment="记忆键")
    memory_value = Column(Text, nullable=False, comment="记忆值")
    category = Column(String(50), default="preference", comment="类别: preference/goal/weakness/style")
    confidence = Column(Float, default=0.7, comment="置信度")
    status = Column(String(20), default="active", index=True, comment="状态: active, ignored")
    is_locked = Column(Integer, default=0, comment="是否锁定（1=锁定，不自动覆盖）")
    source_conversation_id = Column(Integer, ForeignKey("chat_conversations.id", ondelete="SET NULL"))
    material_id = Column(Integer, nullable=True, comment="关联资料ID，用于分科记忆隔离")
    memory_type = Column(String(20), default="semantic", comment="记忆类型: semantic(永久) / episodic(会话级，可衰减)")
    last_seen_at = Column(DateTime, server_default=func.now(), comment="最近更新时间")
    created_at = Column(DateTime, server_default=func.now(), comment="创建时间")
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), comment="更新时间")
