ALTER TABLE learning_events ADD COLUMN IF NOT EXISTS source VARCHAR(50);
ALTER TABLE learning_events ADD COLUMN IF NOT EXISTS dedupe_key VARCHAR(160);
ALTER TABLE learning_events ADD COLUMN IF NOT EXISTS goal_id INTEGER;
ALTER TABLE learning_events ADD COLUMN IF NOT EXISTS task_id INTEGER;
ALTER TABLE learning_events ADD COLUMN IF NOT EXISTS note_id INTEGER;
ALTER TABLE learning_events ADD COLUMN IF NOT EXISTS material_id INTEGER;
ALTER TABLE learning_events ADD COLUMN IF NOT EXISTS chapter_id INTEGER;
ALTER TABLE learning_events ADD COLUMN IF NOT EXISTS wrong_question_id INTEGER;
ALTER TABLE learning_events ADD COLUMN IF NOT EXISTS session_id VARCHAR(50);

CREATE INDEX IF NOT EXISTS ix_learning_events_user_type_time
ON learning_events(user_id, event_type, timestamp);

CREATE INDEX IF NOT EXISTS ix_learning_events_dedupe_key
ON learning_events(dedupe_key);
