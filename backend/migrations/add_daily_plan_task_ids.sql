-- Add task_ids field to daily_plans table for calendar-task bidirectional binding
-- This allows daily plans to reference specific goal tasks

ALTER TABLE daily_plans ADD COLUMN task_ids TEXT DEFAULT NULL COMMENT 'JSON array of task IDs linked to this daily plan';
