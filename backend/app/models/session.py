"""学习会话相关模型"""
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base


class StudySession(Base):
    """学习会话表"""
    __tablename__ = "study_sessions"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    chapter_id = Column(Integer, ForeignKey("chapters.id"), comment="学习的章节")
    task_id = Column(Integer, ForeignKey("tasks.id"), comment="关联的任务")
    session_type = Column(String(20), comment="类型: new_learning, review, practice")
    started_at = Column(DateTime, comment="开始时间")
    ended_at = Column(DateTime, comment="结束时间")
    summary = Column(Text, comment="用户的总结")
    ai_feedback = Column(Text, comment="AI 的反馈")
    created_at = Column(DateTime, server_default=func.now(), comment="创建时间")
    
    # 关联关系
    chapter = relationship("Chapter", back_populates="study_sessions")
    task = relationship("Task", back_populates="study_sessions")
    conversations = relationship("Conversation", back_populates="session", cascade="all, delete-orphan")
    quiz_records = relationship("QuizRecord", back_populates="session")
    pomodoros = relationship("Pomodoro", back_populates="session")


class Conversation(Base):
    """对话记录表"""
    __tablename__ = "conversations"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(Integer, ForeignKey("study_sessions.id"), nullable=False, comment="所属学习会话")
    role = Column(String(20), nullable=False, comment="角色: user, assistant")
    content = Column(Text, nullable=False, comment="消息内容")
    message_type = Column(String(20), comment="类型: review, explain, feynman, socratic, quiz")
    created_at = Column(DateTime, server_default=func.now(), comment="时间")
    
    # 关联关系
    session = relationship("StudySession", back_populates="conversations")
