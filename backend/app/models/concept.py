"""概念图谱模型：知识点成为一等实体（决策 D2）。

三张表构成轻量领域图：
- concepts：概念节点（含归一化名用于去重；不再拥有用户学习状态）。
- concept_edges：概念间关系（prerequisite_of / related_to）。
- concept_links：既有实体（章节/笔记/题目/错题/卡片）挂接到概念。
"""
from __future__ import annotations

from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.sql import func

from app.database import Base


class Concept(Base):
    """概念（知识点）节点。"""

    __tablename__ = "concepts"
    __table_args__ = (
        UniqueConstraint("user_id", "name_normalized", name="uq_concepts_user_name"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    name = Column(String(120), nullable=False, comment="概念名（展示用）")
    name_normalized = Column(String(120), nullable=False, index=True, comment="归一化名（去重用）")
    description = Column(Text, nullable=True, comment="概念简述")
    mastery = Column(
        Float,
        nullable=False,
        default=0.0,
        comment="Legacy compatibility only; authoritative state is user_concept_state",
    )
    source = Column(String(40), nullable=False, default="extract", comment="来源: extract | structure | backfill | manual")
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)


class ConceptEdge(Base):
    """概念间关系边。"""

    __tablename__ = "concept_edges"
    __table_args__ = (
        UniqueConstraint("user_id", "from_concept_id", "to_concept_id", "edge_type", name="uq_concept_edges_pair"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    from_concept_id = Column(Integer, ForeignKey("concepts.id", ondelete="CASCADE"), nullable=False, index=True)
    to_concept_id = Column(Integer, ForeignKey("concepts.id", ondelete="CASCADE"), nullable=False, index=True)
    edge_type = Column(String(30), nullable=False, comment="prerequisite_of | related_to")
    confidence = Column(Float, nullable=False, default=0.6, comment="关系置信度 0-1")
    source = Column(String(40), nullable=False, default="extract")
    created_at = Column(DateTime, server_default=func.now(), nullable=False)


class ConceptLink(Base):
    """既有实体挂接到概念。"""

    __tablename__ = "concept_links"
    __table_args__ = (
        UniqueConstraint("user_id", "concept_id", "target_type", "target_id", name="uq_concept_links_target"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    concept_id = Column(Integer, ForeignKey("concepts.id", ondelete="CASCADE"), nullable=False, index=True)
    target_type = Column(String(30), nullable=False, comment="chapter | note | question | wrong_question | anki_card")
    target_id = Column(Integer, nullable=False, index=True)
    link_type = Column(String(30), nullable=False, default="covers", comment="covers | explains | tests | drills")
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
