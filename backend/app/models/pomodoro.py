"""番茄钟相关模型"""
from __future__ import annotations

from datetime import datetime
from typing import Optional, TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from ..database import Base

if TYPE_CHECKING:
    from .session import StudySession
    from .material import Chapter
    from .goal import Task


class Pomodoro(Base):
    """番茄钟记录表"""
    __tablename__ = "pomodoros"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id"),
        nullable=False,
        default=1,
        index=True,
        comment="所属用户",
    )
    session_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("study_sessions.id"),
        comment="关联学习会话",
        nullable=True,
    )
    chapter_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("chapters.id"),
        comment="关联章节",
        nullable=True,
    )
    task_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("tasks.id"),
        comment="关联任务",
        nullable=True,
    )
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, comment="开始时间", nullable=True)
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime, comment="结束时间", nullable=True)
    task_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True, comment="任务名称（前端传入）")
    duration: Mapped[float] = mapped_column(Float, default=25.0, comment="时长（分钟）")
    completed: Mapped[bool] = mapped_column(Boolean, default=False, comment="是否完成（未中断）")
    stop_reason: Mapped[Optional[str]] = mapped_column(
        String(20),
        nullable=True,
        comment="停止原因: early_done(提前完成) / interrupted(临时中断) / distracted(状态不好/走神)"
    )
    note: Mapped[Optional[str]] = mapped_column(Text, comment="备注", nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), comment="创建时间")

    # 关联关系
    session: Mapped[Optional["StudySession"]] = relationship("StudySession", back_populates="pomodoros")
    chapter: Mapped[Optional["Chapter"]] = relationship("Chapter", back_populates="pomodoros")
    task: Mapped[Optional["Task"]] = relationship("Task", back_populates="pomodoros")


class DailyStat(Base):
    """每日统计表"""
    __tablename__ = "daily_stats"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id"),
        nullable=False,
        default=1,
        index=True,
        comment="所属用户",
    )
    date: Mapped[Optional[datetime]] = mapped_column(DateTime, comment="日期", nullable=True)
    study_time: Mapped[int] = mapped_column(Integer, default=0, comment="总学习时间（分钟）")
    pomodoro_count: Mapped[int] = mapped_column(Integer, default=0, comment="番茄数量")
    questions_attempted: Mapped[int] = mapped_column(Integer, default=0, comment="尝试题目数")
    questions_correct: Mapped[int] = mapped_column(Integer, default=0, comment="正确题目数")
    chapters_reviewed: Mapped[int] = mapped_column(Integer, default=0, comment="复习章节数")
    new_chapters_learned: Mapped[int] = mapped_column(Integer, default=0, comment="新学章节数")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), comment="创建时间")
