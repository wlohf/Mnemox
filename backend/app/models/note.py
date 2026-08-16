"""笔记相关模型"""
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Index
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
    source_path = Column(String(500), nullable=True, index=True, comment="外部来源路径（Obsidian vault 相对路径，用于增量同步幂等键）")
    source_vault_id = Column(String(160), nullable=True, index=True, comment="外部 vault 的稳定文件系统标识")
    source_file_id = Column(String(160), nullable=True, index=True, comment="vault 内文件的稳定文件系统标识")
    source_sync_hash = Column(String(64), nullable=True, comment="上次已接收 vault 内容的 SHA-256 摘要")
    source_sync_state = Column(String(20), nullable=True, index=True, comment="active/missing/conflict")
    source_conflict_title = Column(String(200), nullable=True, comment="冲突时保留的 vault 标题")
    source_conflict_content = Column(Text, nullable=True, comment="冲突时保留的 vault 正文")
    source_conflict_hash = Column(String(64), nullable=True, comment="冲突 vault 内容的 SHA-256 摘要")
    created_at = Column(DateTime, server_default=func.now(), comment="创建时间")
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), comment="更新时间")
    
    __table_args__ = (
        Index(
            "uq_notes_source_identity",
            "user_id",
            "source_vault_id",
            "source_file_id",
            unique=True,
        ),
    )

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
