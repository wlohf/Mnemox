"""番茄钟相关模型"""
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Boolean
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base


class Pomodoro(Base):
    """番茄钟记录表"""
    __tablename__ = "pomodoros"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(Integer, ForeignKey("study_sessions.id"), comment="关联学习会话")
    chapter_id = Column(Integer, ForeignKey("chapters.id"), comment="关联章节")
    task_id = Column(Integer, ForeignKey("tasks.id"), comment="关联任务")
    started_at = Column(DateTime, comment="开始时间")
    ended_at = Column(DateTime, comment="结束时间")
    duration = Column(Integer, default=25, comment="时长（分钟）")
    completed = Column(Boolean, default=False, comment="是否完成（未中断）")
    note = Column(Text, comment="备注")
    created_at = Column(DateTime, server_default=func.now(), comment="创建时间")
    
    # 关联关系
    session = relationship("StudySession", back_populates="pomodoros")
    chapter = relationship("Chapter", back_populates="pomodoros")
    task = relationship("Task", back_populates="pomodoros")


class DailyStat(Base):
    """每日统计表"""
    __tablename__ = "daily_stats"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(DateTime, unique=True, comment="日期")
    study_time = Column(Integer, default=0, comment="总学习时间（分钟）")
    pomodoro_count = Column(Integer, default=0, comment="番茄数量")
    questions_attempted = Column(Integer, default=0, comment="尝试题目数")
    questions_correct = Column(Integer, default=0, comment="正确题目数")
    chapters_reviewed = Column(Integer, default=0, comment="复习章节数")
    new_chapters_learned = Column(Integer, default=0, comment="新学章节数")
    created_at = Column(DateTime, server_default=func.now(), comment="创建时间")
