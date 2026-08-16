"""AI 记忆模型：会话摘要 + 长期记忆"""
from sqlalchemy import Column, DateTime, Float, ForeignKey, Index, Integer, String, Text
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
    status = Column(String(20), default="active", index=True, comment="状态: active, staged, ignored")
    is_locked = Column(Integer, default=0, comment="是否锁定（1=锁定，不自动覆盖）")
    source_conversation_id = Column(Integer, ForeignKey("chat_conversations.id", ondelete="SET NULL"))
    source_type = Column(String(50), nullable=True, comment="来源类型: learning_event/agent/user/system")
    source_id = Column(String(100), nullable=True, comment="来源对象ID或幂等键")
    evidence = Column(Text, nullable=True, comment="JSON 证据摘要，避免存放原始敏感内容")
    expires_at = Column(DateTime, nullable=True, comment="过期时间，可用于临时记忆")
    review_status = Column(String(20), default="confirmed", index=True, comment="审核状态: staged/confirmed/ignored")
    material_id = Column(Integer, nullable=True, comment="关联资料ID，用于分科记忆隔离")
    memory_type = Column(String(20), default="semantic", comment="记忆类型: semantic(永久) / episodic(会话级，可衰减)")
    last_seen_at = Column(DateTime, server_default=func.now(), comment="最近更新时间")
    created_at = Column(DateTime, server_default=func.now(), comment="创建时间")
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), comment="更新时间")


class MemoryDeclaration(Base):
    """用户记忆的可审计声明历史。

    ``UserMemory`` 保留当前可被产品功能读取的有效值；每一次明确的人工
    声明或修订则写入本表。这样不会让后台提炼结果覆盖用户已经确认的陈述，
    同时也能保留更正前后的时间边界和来源。
    """

    __tablename__ = "memory_declarations"
    __table_args__ = (
        Index(
            "ix_memory_declarations_user_memory_observed",
            "user_id",
            "memory_id",
            "observed_at",
        ),
        Index(
            "ix_memory_declarations_user_review_observed",
            "user_id",
            "review_status",
            "observed_at",
        ),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="所属用户",
    )
    memory_id = Column(
        Integer,
        ForeignKey("user_memories.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="对应的当前记忆条目",
    )
    subject = Column(String(160), nullable=False, comment="声明主体")
    predicate = Column(String(80), nullable=False, comment="声明谓词或记忆类别")
    value = Column(Text, nullable=False, comment="声明值")
    valid_from = Column(DateTime, nullable=False, comment="该声明生效时间")
    valid_to = Column(DateTime, nullable=True, comment="被后续声明替代的时间")
    observed_at = Column(DateTime, nullable=False, comment="用户确认或观察到的时间")
    confidence = Column(Float, nullable=False, default=0.8, comment="置信度")
    review_status = Column(
        String(20),
        nullable=False,
        default="confirmed",
        index=True,
        comment="审核状态: confirmed/superseded/ignored",
    )
    source_event_id = Column(Integer, nullable=True, comment="关联学习事件ID")
    source_type = Column(String(50), nullable=False, default="manual", comment="来源类型")
    source_id = Column(String(160), nullable=True, comment="来源对象或幂等标识")
    evidence = Column(Text, nullable=True, comment="JSON 证据摘要，不保留原始聊天全文")
    created_by = Column(String(30), nullable=False, default="user", comment="创建者: user/agent/system")
    model_version = Column(String(80), nullable=True, comment="模型或规则版本")
    supersedes_id = Column(
        Integer,
        ForeignKey("memory_declarations.id", ondelete="SET NULL"),
        nullable=True,
        comment="被本声明替代的上一条声明",
    )
    created_at = Column(DateTime, server_default=func.now(), nullable=False, comment="创建时间")
