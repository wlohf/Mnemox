"""笔记相关模型"""
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base


class Note(Base):
    """笔记表"""
    __tablename__ = "notes"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, default=1, comment="所属用户")
    material_id = Column(Integer, ForeignKey("materials.id"), comment="关联资料")
    chapter_id = Column(Integer, ForeignKey("chapters.id"), comment="关联章节")
    title = Column(String(200), comment="笔记标题")
    content = Column(Text, comment="Markdown 内容")
    tags = Column(Text, comment="JSON 标签数组")
    note_type = Column(String(20), comment="笔记类型: general, summary, review")
    created_at = Column(DateTime, server_default=func.now(), comment="创建时间")
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), comment="更新时间")
    
    # 关联关系
    material = relationship("Material", back_populates="notes")
    chapter = relationship("Chapter", back_populates="notes")
    links = relationship("NoteLink", back_populates="note", cascade="all, delete-orphan")


class NoteLink(Base):
    """笔记关联对象（任务/会话/资料扩展）"""
    __tablename__ = "note_links"

    id = Column(Integer, primary_key=True, autoincrement=True)
    note_id = Column(Integer, ForeignKey("notes.id", ondelete="CASCADE"), nullable=False)
    link_type = Column(String(30), nullable=False, comment="task/session/material/chapter")
    link_id = Column(Integer, nullable=False, comment="关联对象ID")
    created_at = Column(DateTime, server_default=func.now(), comment="创建时间")

    note = relationship("Note", back_populates="links")
