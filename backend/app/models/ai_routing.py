"""AI 场景路由配置模型"""
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.sql import func
from app.database import Base


class AIRoutingSetting(Base):
    """不同业务场景可绑定不同 AI 提供商。"""
    __tablename__ = "ai_routing_settings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, default=1, comment="所属用户")
    scenario = Column(String(50), nullable=False, comment="场景标识")
    provider_name = Column(String(50), ForeignKey("ai_provider_settings.provider_name"), nullable=True, comment="绑定提供商")
    model = Column(String(100), nullable=True, comment="绑定模型；为空时使用提供商默认模型")
    created_at = Column(DateTime, server_default=func.now(), comment="创建时间")
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), comment="更新时间")
