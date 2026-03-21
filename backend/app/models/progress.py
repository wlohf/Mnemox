"""学习进度引擎相关模型"""
from sqlalchemy import Column, Integer, String, Text, DateTime, Float, Boolean, ForeignKey
from sqlalchemy.sql import func
from app.database import Base


class MaterialProfile(Base):
    """资料学习画像（教材识别与结构化大纲）"""
    __tablename__ = "material_profiles"

    id = Column(Integer, primary_key=True, autoincrement=True)
    material_id = Column(Integer, ForeignKey("materials.id", ondelete="CASCADE"), unique=True, nullable=False)
    is_textbook = Column(Boolean, default=False, comment="是否教材型资料")
    confidence = Column(Float, default=0.0, comment="识别置信度 0-1")
    source = Column(String(20), default="ai", comment="来源: ai/manual")
    structure_json = Column(Text, comment="JSON: 章节/知识点/题型结构")
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    created_at = Column(DateTime, server_default=func.now())


class OutputEvaluation(Base):
    """学习产出评估记录"""
    __tablename__ = "output_evaluations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    task_id = Column(Integer, ForeignKey("tasks.id", ondelete="SET NULL"))
    material_id = Column(Integer, ForeignKey("materials.id", ondelete="SET NULL"))
    score = Column(Integer, default=0)
    verdict = Column(String(30), comment="通过/接近通过/需改进")
    strengths = Column(Text, comment="JSON 列表")
    gaps = Column(Text, comment="JSON 列表")
    next_actions = Column(Text, comment="JSON 列表")
    created_at = Column(DateTime, server_default=func.now())
