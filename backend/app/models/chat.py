"""AI 对话相关模型：项目、对话、消息"""
from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base


class ChatProject(Base):
    """对话项目表"""
    __tablename__ = "chat_projects"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, default=1, index=True, comment="所属用户")
    name = Column(String(200), nullable=False, comment="项目名称")
    description = Column(Text, comment="项目描述")
    default_instructions = Column(Text, comment="默认系统指令")
    color = Column(String(20), default="#1890ff", comment="项目颜色")
    is_archived = Column(Boolean, default=False, comment="是否归档")
    created_at = Column(DateTime, server_default=func.now(), comment="创建时间")
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), comment="��新时间")

    conversations = relationship("ChatConversation", back_populates="project")
    materials = relationship("ChatProjectMaterial", back_populates="project", cascade="all, delete-orphan")


class ChatProjectMaterial(Base):
    """项目-资料关联表"""
    __tablename__ = "chat_project_materials"

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey("chat_projects.id", ondelete="CASCADE"), nullable=False)
    material_id = Column(Integer, ForeignKey("materials.id", ondelete="CASCADE"), nullable=False)
    created_at = Column(DateTime, server_default=func.now())

    project = relationship("ChatProject", back_populates="materials")


class ChatConversation(Base):
    """对话表"""
    __tablename__ = "chat_conversations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, default=1, index=True, comment="所属用户")
    project_id = Column(Integer, ForeignKey("chat_projects.id", ondelete="SET NULL"), nullable=True, index=True, comment="所属项目")
    title = Column(String(200), default="新对话", comment="对话标题")
    summary = Column(Text, comment="对话摘要")
    is_pinned = Column(Boolean, default=False, comment="是否置顶")
    created_at = Column(DateTime, server_default=func.now(), comment="创建时间")
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), comment="更新时间")

    project = relationship("ChatProject", back_populates="conversations")
    messages = relationship("ChatMessage", back_populates="conversation", cascade="all, delete-orphan", order_by="ChatMessage.id")


class ChatMessage(Base):
    """对话消息表"""
    __tablename__ = "chat_messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    conversation_id = Column(Integer, ForeignKey("chat_conversations.id", ondelete="CASCADE"), nullable=False, index=True)
    role = Column(String(20), nullable=False, comment="角色: user/assistant")
    content = Column(Text, nullable=False, comment="消息内容")
    image_data = Column(Text, comment="图片数据 JSON")
    created_at = Column(DateTime, server_default=func.now(), comment="创建时间")

    conversation = relationship("ChatConversation", back_populates="messages")
