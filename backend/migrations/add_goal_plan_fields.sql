-- 为 Goal 表添加学习计划相关字段
-- 执行方式: psql -U your_user -d your_db -f add_goal_plan_fields.sql

ALTER TABLE goals 
ADD COLUMN IF NOT EXISTS plan_total_days INTEGER,
ADD COLUMN IF NOT EXISTS plan_current_chapter_id INTEGER REFERENCES chapters(id),
ADD COLUMN IF NOT EXISTS plan_study_days_per_week INTEGER,
ADD COLUMN IF NOT EXISTS plan_start_date DATE,
ADD COLUMN IF NOT EXISTS plan_last_generated_week DATE;

COMMENT ON COLUMN goals.plan_total_days IS '计划总天数';
COMMENT ON COLUMN goals.plan_current_chapter_id IS '当前进度章节';
COMMENT ON COLUMN goals.plan_study_days_per_week IS '每周学习天数';
COMMENT ON COLUMN goals.plan_start_date IS '计划开始日期';
COMMENT ON COLUMN goals.plan_last_generated_week IS '最后生成任务的周起始日期';
