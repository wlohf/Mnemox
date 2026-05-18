-- User-scoping and Agent runtime fields for PostgreSQL deployments.
-- SQLite development databases are handled by app.database._run_lightweight_migrations.
-- Run with: psql -U your_user -d your_db -f backend/migrations/add_user_scope_and_agent_fields.sql

ALTER TABLE materials ADD COLUMN IF NOT EXISTS user_id INTEGER NOT NULL DEFAULT 1 REFERENCES users(id);
ALTER TABLE goals ADD COLUMN IF NOT EXISTS user_id INTEGER NOT NULL DEFAULT 1 REFERENCES users(id);
ALTER TABLE chat_projects ADD COLUMN IF NOT EXISTS user_id INTEGER NOT NULL DEFAULT 1 REFERENCES users(id);
ALTER TABLE chat_conversations ADD COLUMN IF NOT EXISTS user_id INTEGER NOT NULL DEFAULT 1 REFERENCES users(id);
ALTER TABLE notes ADD COLUMN IF NOT EXISTS user_id INTEGER NOT NULL DEFAULT 1 REFERENCES users(id);
ALTER TABLE pomodoros ADD COLUMN IF NOT EXISTS user_id INTEGER NOT NULL DEFAULT 1 REFERENCES users(id);
ALTER TABLE daily_stats ADD COLUMN IF NOT EXISTS user_id INTEGER NOT NULL DEFAULT 1 REFERENCES users(id);
ALTER TABLE study_sessions ADD COLUMN IF NOT EXISTS user_id INTEGER NOT NULL DEFAULT 1 REFERENCES users(id);
ALTER TABLE questions ADD COLUMN IF NOT EXISTS user_id INTEGER NOT NULL DEFAULT 1 REFERENCES users(id);
ALTER TABLE wrong_questions ADD COLUMN IF NOT EXISTS user_id INTEGER NOT NULL DEFAULT 1 REFERENCES users(id);
ALTER TABLE review_schedule ADD COLUMN IF NOT EXISTS user_id INTEGER NOT NULL DEFAULT 1 REFERENCES users(id);
ALTER TABLE ai_provider_settings ADD COLUMN IF NOT EXISTS user_id INTEGER NOT NULL DEFAULT 1 REFERENCES users(id);
ALTER TABLE ai_routing_settings ADD COLUMN IF NOT EXISTS user_id INTEGER NOT NULL DEFAULT 1 REFERENCES users(id);
ALTER TABLE user_memories ADD COLUMN IF NOT EXISTS user_id INTEGER NOT NULL DEFAULT 1 REFERENCES users(id);
ALTER TABLE conversation_summaries ADD COLUMN IF NOT EXISTS user_id INTEGER NOT NULL DEFAULT 1 REFERENCES users(id);
ALTER TABLE daily_plans ADD COLUMN IF NOT EXISTS user_id INTEGER NOT NULL DEFAULT 1 REFERENCES users(id);
ALTER TABLE agent_jobs ADD COLUMN IF NOT EXISTS user_id INTEGER NOT NULL DEFAULT 1 REFERENCES users(id);
ALTER TABLE agent_execution_logs ADD COLUMN IF NOT EXISTS user_id INTEGER NOT NULL DEFAULT 1 REFERENCES users(id);

CREATE INDEX IF NOT EXISTS ix_materials_user_id ON materials(user_id);
CREATE INDEX IF NOT EXISTS ix_goals_user_id ON goals(user_id);
CREATE INDEX IF NOT EXISTS ix_chat_projects_user_id ON chat_projects(user_id);
CREATE INDEX IF NOT EXISTS ix_chat_conversations_user_id ON chat_conversations(user_id);
CREATE INDEX IF NOT EXISTS ix_notes_user_id ON notes(user_id);
CREATE INDEX IF NOT EXISTS ix_pomodoros_user_id ON pomodoros(user_id);
CREATE INDEX IF NOT EXISTS ix_study_sessions_user_id ON study_sessions(user_id);
CREATE INDEX IF NOT EXISTS ix_questions_user_id ON questions(user_id);
CREATE INDEX IF NOT EXISTS ix_wrong_questions_user_id ON wrong_questions(user_id);
CREATE INDEX IF NOT EXISTS ix_review_schedule_user_id ON review_schedule(user_id);
CREATE INDEX IF NOT EXISTS ix_user_memories_user_id ON user_memories(user_id);
CREATE INDEX IF NOT EXISTS ix_conversation_summaries_user_id ON conversation_summaries(user_id);
CREATE INDEX IF NOT EXISTS ix_daily_plans_user_id ON daily_plans(user_id);
CREATE INDEX IF NOT EXISTS ix_agent_jobs_user_id ON agent_jobs(user_id);
CREATE INDEX IF NOT EXISTS ix_agent_execution_logs_user_id ON agent_execution_logs(user_id);

ALTER TABLE conversation_summaries ADD COLUMN IF NOT EXISTS questions_asked TEXT;
ALTER TABLE conversation_summaries ADD COLUMN IF NOT EXISTS confusions TEXT;
ALTER TABLE conversation_summaries ADD COLUMN IF NOT EXISTS misconceptions TEXT;
ALTER TABLE conversation_summaries ADD COLUMN IF NOT EXISTS review_prompts TEXT;
ALTER TABLE conversation_summaries ADD COLUMN IF NOT EXISTS reflection_turn_count INTEGER DEFAULT 0;
ALTER TABLE user_memories ADD COLUMN IF NOT EXISTS material_id INTEGER;
ALTER TABLE user_memories ADD COLUMN IF NOT EXISTS memory_type VARCHAR(20) DEFAULT 'semantic';

ALTER TABLE notes ADD COLUMN IF NOT EXISTS note_type VARCHAR(20);
ALTER TABLE notes ADD COLUMN IF NOT EXISTS material_id INTEGER REFERENCES materials(id);
ALTER TABLE notes ADD COLUMN IF NOT EXISTS chapter_id INTEGER REFERENCES chapters(id);
ALTER TABLE notes ADD COLUMN IF NOT EXISTS tags TEXT;
ALTER TABLE notes ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP;
UPDATE notes SET updated_at = created_at WHERE updated_at IS NULL;

ALTER TABLE daily_plans ADD COLUMN IF NOT EXISTS task_ids TEXT;
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'uq_dailyplan_user_date'
    ) THEN
        ALTER TABLE daily_plans ADD CONSTRAINT uq_dailyplan_user_date UNIQUE (user_id, date);
    END IF;
END $$;

ALTER TABLE agent_jobs ADD COLUMN IF NOT EXISTS payload JSONB DEFAULT '{}'::jsonb;
ALTER TABLE agent_jobs ADD COLUMN IF NOT EXISTS result JSONB;
ALTER TABLE agent_jobs ADD COLUMN IF NOT EXISTS summary TEXT;
ALTER TABLE agent_jobs ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;
ALTER TABLE agent_execution_logs ADD COLUMN IF NOT EXISTS metadata JSONB;
