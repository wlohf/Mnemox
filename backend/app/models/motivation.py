"""激励语录相关模型"""
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey
from sqlalchemy.sql import func
from app.database import Base


class MotivationQuote(Base):
    """激励语录表"""
    __tablename__ = "motivation_quotes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, default=1, index=True, comment="所属用户")
    content = Column(Text, nullable=False, comment="语录内容")
    author = Column(String(100), nullable=True, comment="作者/来源")
    source_type = Column(String(20), default="preset", comment="来源: preset/custom/ai")
    created_at = Column(DateTime, server_default=func.now(), comment="创建时间")


class MotivationSettings(Base):
    """激励语录展示设置"""
    __tablename__ = "motivation_settings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, unique=True, index=True, comment="所属用户")
    display_mode = Column(String(20), nullable=False, default="auto", comment="展示模式: auto/manual")
    selected_quote_id = Column(Integer, ForeignKey("motivation_quotes.id"), nullable=True, comment="手动指定语录")
    sort_mode = Column(String(30), nullable=False, default="created_desc", comment="排序方式")
    rotation_seconds = Column(Integer, nullable=False, default=10800, comment="轮换周期（秒）")
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), comment="更新时间")
