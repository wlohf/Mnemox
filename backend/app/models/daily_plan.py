"""每日计划/复盘记录模型（用于 Obsidian 风格日历）。"""

from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, UniqueConstraint, text
from sqlalchemy.sql import func

from app.database import Base


class DailyPlan(Base):
    """每日计划表（按日期唯一）"""

    __tablename__ = "daily_plans"
    __table_args__ = (
        UniqueConstraint('user_id', 'date', name='uq_dailyplan_user_date'),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True, comment="所属用户")
    # YYYY-MM-DD
    date = Column(String(10), nullable=False, comment="日期(YYYY-MM-DD)")
    content = Column(Text, nullable=False, default="", comment="计划/记录内容")
    version = Column(Integer, nullable=False, default=1, server_default=text("1"))
    __mapper_args__ = {"version_id_col": version}
    task_ids = Column(Text, nullable=True, comment="JSON array of task IDs linked to this daily plan")
    created_at = Column(DateTime, server_default=func.now(), comment="创建时间")
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), comment="更新时间")


class DailyPlanRevision(Base):
    __tablename__ = "daily_plan_revisions"
    __table_args__ = (UniqueConstraint("plan_id", "version", name="uq_plan_revision"),)
    id = Column(Integer, primary_key=True)
    plan_id = Column(Integer, ForeignKey("daily_plans.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    version = Column(Integer, nullable=False)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
