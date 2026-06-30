-- Phase 1 autonomous coach kernel tables.
-- PostgreSQL migration helper. SQLite dev databases are handled by Base.metadata.create_all.

CREATE TABLE IF NOT EXISTS coach_events (
    id VARCHAR(40) PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    event_type VARCHAR(100) NOT NULL,
    source VARCHAR(50) NOT NULL,
    severity VARCHAR(20) NOT NULL DEFAULT 'info',
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    dedupe_key VARCHAR(160),
    occurred_at TIMESTAMP NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_coach_events_user_id ON coach_events(user_id);
CREATE INDEX IF NOT EXISTS ix_coach_events_event_type ON coach_events(event_type);
CREATE INDEX IF NOT EXISTS ix_coach_events_dedupe_key ON coach_events(dedupe_key);
CREATE INDEX IF NOT EXISTS ix_coach_events_occurred_at ON coach_events(occurred_at);

CREATE TABLE IF NOT EXISTS coach_nudges (
    id VARCHAR(40) PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    event_id VARCHAR(40),
    skill_id VARCHAR(80) NOT NULL,
    channel VARCHAR(40) NOT NULL,
    priority VARCHAR(20) NOT NULL,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    suggested_action JSONB NOT NULL DEFAULT '{}'::jsonb,
    route VARCHAR(200),
    requires_confirmation BOOLEAN NOT NULL DEFAULT FALSE,
    draft JSONB,
    explainability JSONB,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    expires_at TIMESTAMP,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_coach_nudges_user_id ON coach_nudges(user_id);
CREATE INDEX IF NOT EXISTS ix_coach_nudges_event_id ON coach_nudges(event_id);
CREATE INDEX IF NOT EXISTS ix_coach_nudges_skill_id ON coach_nudges(skill_id);
CREATE INDEX IF NOT EXISTS ix_coach_nudges_status ON coach_nudges(status);

CREATE TABLE IF NOT EXISTS coach_preferences (
    user_id INTEGER PRIMARY KEY REFERENCES users(id),
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    proactive_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    desktop_notifications_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    quiet_hours_start VARCHAR(5),
    quiet_hours_end VARCHAR(5),
    max_nudges_per_day INTEGER NOT NULL DEFAULT 3,
    min_minutes_between_nudges INTEGER NOT NULL DEFAULT 60,
    allowed_channels JSONB NOT NULL DEFAULT '[]'::jsonb,
    disabled_skill_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS coach_workflows (
    id VARCHAR(40) PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    workflow_type VARCHAR(80) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'active',
    current_step VARCHAR(80) NOT NULL DEFAULT 'start',
    state JSONB NOT NULL DEFAULT '{}'::jsonb,
    pending_draft JSONB,
    last_event_id VARCHAR(40),
    started_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_coach_workflows_user_id ON coach_workflows(user_id);
CREATE INDEX IF NOT EXISTS ix_coach_workflows_workflow_type ON coach_workflows(workflow_type);
CREATE INDEX IF NOT EXISTS ix_coach_workflows_status ON coach_workflows(status);
CREATE INDEX IF NOT EXISTS ix_coach_workflows_last_event_id ON coach_workflows(last_event_id);
CREATE INDEX IF NOT EXISTS ix_coach_workflows_started_at ON coach_workflows(started_at);
