"""学习资料相关模型"""
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Float
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base


class Material(Base):
    """学习资料表"""
    __tablename__ = "materials"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, default=1, index=True, comment="所属用户")
    title = Column(String(200), nullable=False, comment="资料标题")
    file_path = Column(String(500), comment="文件路径")
    file_type = Column(String(20), comment="文件类型: pdf, docx, md, txt")
    file_hash = Column(String(64), index=True, comment="文件内容哈希 (sha256)")
    content_hash = Column(String(64), index=True, comment="解析文本哈希 (sha256)")
    content = Column(Text, comment="解析后的文本内容")
    content_status = Column(String(20), default="pending", comment="内容状态: pending, extracted, failed")
    created_at = Column(DateTime, server_default=func.now(), comment="创建时间")
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), comment="更新时间")
    
    # 关联关系
    chapters = relationship("Chapter", back_populates="material", cascade="all, delete-orphan")
    goals = relationship("Goal", back_populates="material", cascade="all, delete-orphan")
    notes = relationship("Note", back_populates="material")


class Chapter(Base):
    """章节/知识点表"""
    __tablename__ = "chapters"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    material_id = Column(Integer, ForeignKey("materials.id"), nullable=False, index=True, comment="所属资料")
    parent_id = Column(Integer, ForeignKey("chapters.id"), comment="父章节ID（支持层级结构）")
    title = Column(String(200), nullable=False, comment="章节标题")
    content = Column(Text, comment="章节内容")
    order_index = Column(Integer, comment="章节顺序")
    mastery_level = Column(Float, default=0.0, comment="掌握程度 0-100")
    created_at = Column(DateTime, server_default=func.now(), comment="创建时间")
    
    # 关联关系
    material = relationship("Material", back_populates="chapters")
    parent = relationship("Chapter", remote_side=[id], back_populates="children")
    children = relationship("Chapter", back_populates="parent", cascade="all, delete-orphan")
    questions = relationship("Question", back_populates="chapter")
    study_sessions = relationship("StudySession", back_populates="chapter")
    pomodoros = relationship("Pomodoro", back_populates="chapter")
    notes = relationship("Note", back_populates="chapter")


# 为了避免循环导入，这里先导入其他模型
from app.models.goal import Goal
from app.models.session import StudySession
from app.models.question import Question
from app.models.pomodoro import Pomodoro
from app.models.note import Note
