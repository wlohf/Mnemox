"""SQL authority for provisional understanding and rebuildable episode results."""
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.sql import func
from app.database import Base


class UnderstandingPreference(Base):
    __tablename__ = 'understanding_preferences'
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), primary_key=True)
    analysis_enabled = Column(Boolean, nullable=False, default=False)
    graph_enabled = Column(Boolean, nullable=False, default=False)
    consume_enabled = Column(Boolean, nullable=False, default=False)
    revision = Column(Integer, nullable=False, default=1)


class Experience(Base):
    __tablename__ = 'understanding_experiences'
    __table_args__ = (UniqueConstraint('user_id', 'source_key', name='uq_understanding_source'),)
    id = Column(String(32), primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    source_key = Column(String(100), nullable=False)
    source_version = Column(String(64), nullable=False)
    evidence_group = Column(String(100), nullable=False)
    kind = Column(String(40), nullable=False)
    occurred_at = Column(DateTime, nullable=True)
    recorded_at = Column(DateTime, nullable=True)
    first_seen_at = Column(DateTime, nullable=False, server_default=func.now())
    payload = Column(JSON, nullable=False, default=dict)
    active = Column(Boolean, nullable=False, default=True)
    excluded = Column(Boolean, nullable=False, default=False)
    # Each version has its own saved extraction. A correction clears it before reads.
    extraction = Column(JSON, nullable=True)
    graph_group = Column(String(160), nullable=True)
    graph_pending = Column(Boolean, nullable=False, default=False)


class BehavioralHypothesis(Base):
    __tablename__ = 'behavioral_hypotheses'
    __table_args__ = (UniqueConstraint('user_id', 'fingerprint', name='uq_hypothesis_fingerprint'),)
    id = Column(String(32), primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    fingerprint = Column(String(64), nullable=False)
    version = Column(Integer, nullable=False, default=1)
    status = Column(String(30), nullable=False, default='candidate')
    review_status = Column(String(30), nullable=False, default='unreviewed')
    statement = Column(Text, nullable=False)
    details = Column(JSON, nullable=False, default=dict)
    assessment = Column(JSON, nullable=False, default=dict)
    discovery_cutoff = Column(DateTime, nullable=False)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())


class HypothesisRevision(Base):
    __tablename__ = 'hypothesis_revisions'
    __table_args__ = (UniqueConstraint('hypothesis_id', 'version', name='uq_hypothesis_revision'),)
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    hypothesis_id = Column(String(32), ForeignKey('behavioral_hypotheses.id', ondelete='CASCADE'), nullable=False, index=True)
    version = Column(Integer, nullable=False)
    reason = Column(String(100), nullable=False)
    snapshot = Column(JSON, nullable=False)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
