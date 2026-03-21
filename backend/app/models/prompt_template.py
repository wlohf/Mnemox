"""用户自定义 Prompt 模板模型"""
from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, ForeignKey
from sqlalchemy.sql import func
from app.database import Base


# 所有支持自定义的模式键，及其默认名称
MODE_KEYS = {
    "coach":      "AI 教练（主对话）",
    "feynman":    "费曼学习法",
    "socratic":   "苏格拉底式提问",
    "review":     "复习引导",
    "quiz":       "出题",
    "error":      "错题分析",
    "summary":    "总结引导",
    "explain":    "概念讲解",
    "distracted_care": "走神关怀（状态不好时）",
    "okr":        "OKR 目标拆解",
}


class PromptTemplate(Base):
    """用户自定义 Prompt 模板表"""
    __tablename__ = "prompt_templates"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True, comment="所属用户")
    mode_key = Column(String(40), nullable=False, comment="模式键，如 feynman/socratic/coach 等")
    content = Column(Text, nullable=False, comment="用户自定义 prompt 内容")
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), comment="最后更新时间")
