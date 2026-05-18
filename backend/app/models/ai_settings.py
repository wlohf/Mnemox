"""AI 提供商设置模型"""
from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Text
from sqlalchemy.sql import func
from app.database import Base


class AIProviderSetting(Base):
    """AI 提供商设置表"""
    __tablename__ = "ai_provider_settings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, default=1, comment="所属用户")
    provider_name = Column(String(50), nullable=False, comment="提供商标识 (deepseek, openai, claude, gemini, qwen)")
    display_name = Column(String(100), nullable=False, comment="显示名称")
    api_key = Column(String(2000), default="", comment="Encrypted API Key")
    base_url = Column(String(500), default="", comment="API Base URL")
    model = Column(String(100), default="", comment="模型名称")
    available_models = Column(Text, default="[]", comment="可选模型 JSON 列表")
    is_active = Column(Boolean, default=False, comment="是否为当前激活的提供商")
    enabled = Column(Boolean, default=True, comment="是否启用")
    created_at = Column(DateTime, server_default=func.now(), comment="创建时间")
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), comment="更新时间")
