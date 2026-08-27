"""Autonomous coach runtime models."""
from __future__ import annotations

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.sql import func

from app.database import Base


class CoachEvent(Base):
    """Normalized user-scoped signal consumed by the coach policy."""

    __tablename__ = "coach_events"

    id = Column(String(40), primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    event_type = Column(String(100), nullable=False, index=True)
    source = Column(String(50), nullable=False)
    severity = Column(String(20), nullable=False, default="info")
    payload = Column(JSON, nullable=False, default=dict)
    dedupe_key = Column(String(160), nullable=True, index=True)
    occurred_at = Column(DateTime, nullable=False, index=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)


class CoachNudge(Base):
    """Generated coach output shown in app, chat, agent panel, or desktop."""

    __tablename__ = "coach_nudges"

    id = Column(String(40), primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    event_id = Column(String(40), nullable=True, index=True)
    skill_id = Column(String(80), nullable=False, index=True)
    channel = Column(String(40), nullable=False)
    priority = Column(String(20), nullable=False)
    title = Column(Text, nullable=False)
    body = Column(Text, nullable=False)
    suggested_action = Column(JSON, nullable=False, default=dict)
    route = Column(String(200), nullable=True)
    requires_confirmation = Column(Boolean, nullable=False, default=False)
    draft = Column(JSON, nullable=True)
    explainability = Column(JSON, nullable=True)
    status = Column(String(20), nullable=False, default="pending", index=True)
    expires_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)


class CoachActionAttempt(Base):
    """One user-initiated attempt to carry a Coach nudge into real study work.

    A nudge is a recommendation; an attempt is the durable bridge from that
    recommendation to a domain event such as a Pomodoro or a completed review.
    Keeping it separate means the recommendation remains replayable even when
    the user leaves and later returns to the action.
    """

    __tablename__ = "coach_action_attempts"
    __table_args__ = (
        Index("ix_coach_action_attempts_user_nudge_status", "user_id", "nudge_id", "status"),
    )

    id = Column(String(40), primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    nudge_id = Column(String(40), ForeignKey("coach_nudges.id", ondelete="CASCADE"), nullable=False, index=True)
    action_type = Column(String(80), nullable=False, default="open_route")
    route = Column(String(200), nullable=True)
    action_payload = Column(JSON, nullable=False, default=dict)
    status = Column(String(20), nullable=False, default="started", index=True)
    started_at = Column(DateTime, server_default=func.now(), nullable=False, index=True)
    observed_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    abandoned_at = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=True)
    linked_event_id = Column(Integer, ForeignKey("learning_events.id", ondelete="SET NULL"), nullable=True, index=True)
    linked_event_type = Column(String(80), nullable=True)
    outcome_source = Column(String(40), nullable=True)
    outcome_reason = Column(String(120), nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)


class CoachPreference(Base):
    """Per-user coach autonomy and notification preferences."""

    __tablename__ = "coach_preferences"

    user_id = Column(Integer, ForeignKey("users.id"), primary_key=True)
    enabled = Column(Boolean, nullable=False, default=True)
    proactive_enabled = Column(Boolean, nullable=False, default=False)
    desktop_notifications_enabled = Column(Boolean, nullable=False, default=False)
    quiet_hours_start = Column(String(5), nullable=True)
    quiet_hours_end = Column(String(5), nullable=True)
    max_nudges_per_day = Column(Integer, nullable=False, default=3)
    min_minutes_between_nudges = Column(Integer, nullable=False, default=60)
    allowed_channels = Column(JSON, nullable=False, default=list)
    disabled_skill_ids = Column(JSON, nullable=False, default=list)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)


class CoachWorkflow(Base):
    """Durable, confirmation-first coach workflow state."""

    __tablename__ = "coach_workflows"

    id = Column(String(40), primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    workflow_type = Column(String(80), nullable=False, index=True)
    status = Column(String(20), nullable=False, default="active", index=True)
    current_step = Column(String(80), nullable=False, default="start")
    state = Column(JSON, nullable=False, default=dict)
    pending_draft = Column(JSON, nullable=True)
    last_event_id = Column(String(40), nullable=True, index=True)
    started_at = Column(DateTime, server_default=func.now(), nullable=False, index=True)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)
    completed_at = Column(DateTime, nullable=True)


class CoachSkillStats(Base):
    """Aggregated per-user feedback signals for coach policy learning."""

    __tablename__ = "coach_skill_stats"
    __table_args__ = (
        UniqueConstraint("user_id", "skill_id", "channel", "event_type", name="uq_coach_skill_stats_scope"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    skill_id = Column(String(80), nullable=False, index=True)
    channel = Column(String(40), nullable=False, default="", index=True)
    event_type = Column(String(100), nullable=False, default="", index=True)
    shown_count = Column(Integer, nullable=False, default=0)
    accepted_count = Column(Integer, nullable=False, default=0)
    started_count = Column(Integer, nullable=False, default=0)
    completed_count = Column(Integer, nullable=False, default=0)
    abandoned_count = Column(Integer, nullable=False, default=0)
    helpful_count = Column(Integer, nullable=False, default=0)
    snoozed_count = Column(Integer, nullable=False, default=0)
    dismissed_count = Column(Integer, nullable=False, default=0)
    too_disruptive_count = Column(Integer, nullable=False, default=0)
    too_hard_count = Column(Integer, nullable=False, default=0)
    too_easy_count = Column(Integer, nullable=False, default=0)
    irrelevant_count = Column(Integer, nullable=False, default=0)
    not_my_style_count = Column(Integer, nullable=False, default=0)
    recent_score = Column(Float, nullable=False, default=0.0)
    lifetime_score = Column(Float, nullable=False, default=0.0)
    last_shown_at = Column(DateTime, nullable=True)
    last_positive_at = Column(DateTime, nullable=True)
    last_negative_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)
