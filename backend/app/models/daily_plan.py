"""每日计划/复盘记录模型（用于 Obsidian 风格日历）。"""

from sqlalchemy import Column, Integer, String, Text, DateTime
from sqlalchemy.sql import func

from app.database import Base


class DailyPlan(Base):
    """每日计划表（按日期唯一）"""

    __tablename__ = "daily_plans"

    id = Column(Integer, primary_key=True, autoincrement=True)
    # YYYY-MM-DD
    date = Column(String(10), unique=True, nullable=False, comment="日期(YYYY-MM-DD)")
    content = Column(Text, nullable=False, default="", comment="计划/记录内容")
    created_at = Column(DateTime, server_default=func.now(), comment="创建时间")
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), comment="更新时间")

