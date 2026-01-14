"""笔记相关模型"""
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base


class Note(Base):
    """笔记表"""
    __tablename__ = "notes"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    material_id = Column(Integer, ForeignKey("materials.id"), comment="关联资料")
    chapter_id = Column(Integer, ForeignKey("chapters.id"), comment="关联章节")
    title = Column(String(200), comment="笔记标题")
    content = Column(Text, comment="Markdown 内容")
    note_type = Column(String(20), comment="笔记类型: general, summary, review")
    created_at = Column(DateTime, server_default=func.now(), comment="创建时间")
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), comment="更新时间")
    
    # 关联关系
    material = relationship("Material", back_populates="notes")
    chapter = relationship("Chapter", back_populates="notes")
