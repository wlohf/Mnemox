"""Anki 风格记忆卡模型"""
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey
from sqlalchemy.sql import func

from app.database import Base


class AnkiCard(Base):
    """记忆卡片"""
    __tablename__ = "anki_cards"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, default=1, index=True, comment="所属用户")
    front = Column(Text, nullable=False, comment="问题面")
    back = Column(Text, nullable=False, comment="答案面")
    source = Column(String(20), default="manual", index=True, comment="来源: manual | ai")
    tags = Column(String(255), nullable=True, comment="逗号分隔标签")
    note = Column(Text, nullable=True, comment="备注")

    # SM-2 调度字段
    due_at = Column(DateTime, index=True, nullable=False, server_default=func.now(), comment="下次到期时间")
    interval_days = Column(Integer, nullable=False, default=1, comment="间隔天数")
    ease_factor = Column(Integer, nullable=False, default=250, comment="简易系数 *100")
    repetitions = Column(Integer, nullable=False, default=0, comment="连续成功次数")
    last_quality = Column(Integer, nullable=True, comment="最近评分 0-5")

    created_at = Column(DateTime, server_default=func.now(), comment="创建时间")
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), comment="更新时间")
