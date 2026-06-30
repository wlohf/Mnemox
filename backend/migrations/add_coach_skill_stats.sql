-- Add durable per-skill Coach feedback statistics.
-- SQLite development databases are handled by Base.metadata.create_all.

CREATE TABLE IF NOT EXISTS coach_skill_stats (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    skill_id VARCHAR(80) NOT NULL,
    channel VARCHAR(40) NOT NULL DEFAULT '',
    event_type VARCHAR(100) NOT NULL DEFAULT '',
    shown_count INTEGER NOT NULL DEFAULT 0,
    accepted_count INTEGER NOT NULL DEFAULT 0,
    completed_count INTEGER NOT NULL DEFAULT 0,
    helpful_count INTEGER NOT NULL DEFAULT 0,
    snoozed_count INTEGER NOT NULL DEFAULT 0,
    dismissed_count INTEGER NOT NULL DEFAULT 0,
    too_disruptive_count INTEGER NOT NULL DEFAULT 0,
    too_hard_count INTEGER NOT NULL DEFAULT 0,
    too_easy_count INTEGER NOT NULL DEFAULT 0,
    irrelevant_count INTEGER NOT NULL DEFAULT 0,
    not_my_style_count INTEGER NOT NULL DEFAULT 0,
    recent_score REAL NOT NULL DEFAULT 0.0,
    lifetime_score REAL NOT NULL DEFAULT 0.0,
    last_shown_at TIMESTAMP,
    last_positive_at TIMESTAMP,
    last_negative_at TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_coach_skill_stats_scope UNIQUE(user_id, skill_id, channel, event_type)
);

CREATE INDEX IF NOT EXISTS ix_coach_skill_stats_user_id ON coach_skill_stats(user_id);
CREATE INDEX IF NOT EXISTS ix_coach_skill_stats_skill_id ON coach_skill_stats(skill_id);
CREATE INDEX IF NOT EXISTS ix_coach_skill_stats_channel ON coach_skill_stats(channel);
CREATE INDEX IF NOT EXISTS ix_coach_skill_stats_event_type ON coach_skill_stats(event_type);
