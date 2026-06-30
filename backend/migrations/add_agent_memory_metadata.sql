-- UserMemory metadata used by goal-driven Agent long memory.
-- PostgreSQL-safe. SQLite development databases are handled by app.database._run_lightweight_migrations.

ALTER TABLE user_memories ADD COLUMN IF NOT EXISTS source_type VARCHAR(50);
ALTER TABLE user_memories ADD COLUMN IF NOT EXISTS source_id VARCHAR(100);
ALTER TABLE user_memories ADD COLUMN IF NOT EXISTS evidence TEXT;
ALTER TABLE user_memories ADD COLUMN IF NOT EXISTS expires_at TIMESTAMP;
ALTER TABLE user_memories ADD COLUMN IF NOT EXISTS review_status VARCHAR(20) DEFAULT 'confirmed';
ALTER TABLE user_memories ADD COLUMN IF NOT EXISTS material_id INTEGER;
ALTER TABLE user_memories ADD COLUMN IF NOT EXISTS memory_type VARCHAR(20) DEFAULT 'semantic';

CREATE INDEX IF NOT EXISTS ix_user_memories_user_review_status
    ON user_memories(user_id, review_status, status);

CREATE INDEX IF NOT EXISTS ix_user_memories_user_source
    ON user_memories(user_id, source_type, source_id);
