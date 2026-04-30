"""学习目标相关模型"""
from sqlalchemy import Column, Integer, String, Text, Date, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base


class Goal(Base):
    """学习目标表"""
    __tablename__ = "goals"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, default=1, index=True, comment="所属用户")
    material_id = Column(Integer, ForeignKey("materials.id"), comment="关联资料")
    title = Column(String(200), nullable=False, comment="目标标题")
    description = Column(Text, comment="目标描述")
    target_level = Column(String(50), comment="目标掌握程度")
    deadline = Column(Date, comment="截止日期")
    status = Column(String(20), default="active", index=True, comment="状态: active, completed, paused")
    
    # 学习计划字段
    plan_total_days = Column(Integer, comment="计划总天数")
    plan_current_chapter_id = Column(Integer, ForeignKey("chapters.id"), comment="当前进度章节")
    plan_study_days_per_week = Column(Integer, comment="每周学习天数")
    plan_start_date = Column(Date, comment="计划开始日期")
    plan_last_generated_week = Column(Date, comment="最后生成任务的周起始日期")
    
    created_at = Column(DateTime, server_default=func.now(), comment="创建时间")
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), comment="更新时间")

    # 关联关系
    material = relationship("Material", back_populates="goals")
    tasks = relationship("Task", back_populates="goal", cascade="all, delete-orphan")


class Task(Base):
    """OKR 任务表"""
    __tablename__ = "tasks"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    goal_id = Column(Integer, ForeignKey("goals.id"), nullable=False, index=True, comment="所属目标")
    parent_task_id = Column(Integer, ForeignKey("tasks.id"), nullable=True, index=True, comment="父任务（用于子任务）")
    chapter_id = Column(Integer, ForeignKey("chapters.id"), comment="关联章节")
    title = Column(String(200), nullable=False, comment="任务标题")
    description = Column(Text, comment="任务描述")
    task_type = Column(String(20), comment="任务类型: learn, review, practice, summarize")
    planned_date = Column(Date, index=True, comment="计划日期")
    status = Column(String(20), default="pending", index=True, comment="状态: pending, in_progress, completed")
    completed_at = Column(DateTime, comment="完成时间")
    created_at = Column(DateTime, server_default=func.now(), comment="创建时间")
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), comment="更新时间")

    # 关联关系
    goal = relationship("Goal", back_populates="tasks")
    parent_task = relationship("Task", remote_side=[id], back_populates="subtasks")
    subtasks = relationship("Task", back_populates="parent_task", cascade="all")
    study_sessions = relationship("StudySession", back_populates="task")
    pomodoros = relationship("Pomodoro", back_populates="task")
