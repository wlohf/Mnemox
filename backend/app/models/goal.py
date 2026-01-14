"""学习目标相关模型"""
from sqlalchemy import Column, Integer, String, Text, Date, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base


class Goal(Base):
    """学习目标表"""
    __tablename__ = "goals"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    material_id = Column(Integer, ForeignKey("materials.id"), comment="关联资料")
    title = Column(String(200), nullable=False, comment="目标标题")
    description = Column(Text, comment="目标描述")
    target_level = Column(String(50), comment="目标掌握程度")
    deadline = Column(Date, comment="截止日期")
    status = Column(String(20), default="active", comment="状态: active, completed, paused")
    created_at = Column(DateTime, server_default=func.now(), comment="创建时间")
    
    # 关联关系
    material = relationship("Material", back_populates="goals")
    tasks = relationship("Task", back_populates="goal", cascade="all, delete-orphan")


class Task(Base):
    """OKR 任务表"""
    __tablename__ = "tasks"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    goal_id = Column(Integer, ForeignKey("goals.id"), nullable=False, comment="所属目标")
    chapter_id = Column(Integer, ForeignKey("chapters.id"), comment="关联章节")
    title = Column(String(200), nullable=False, comment="任务标题")
    description = Column(Text, comment="任务描述")
    task_type = Column(String(20), comment="任务类型: learn, review, practice, summarize")
    planned_date = Column(Date, comment="计划日期")
    status = Column(String(20), default="pending", comment="状态: pending, in_progress, completed")
    completed_at = Column(DateTime, comment="完成时间")
    created_at = Column(DateTime, server_default=func.now(), comment="创建时间")
    
    # 关联关系
    goal = relationship("Goal", back_populates="tasks")
    study_sessions = relationship("StudySession", back_populates="task")
    pomodoros = relationship("Pomodoro", back_populates="task")
