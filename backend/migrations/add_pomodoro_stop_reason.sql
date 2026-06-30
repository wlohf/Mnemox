-- 迁移：为 pomodoros 表添加 stop_reason 字段
-- 执行时间：2026-03
-- 说明：记录番茄钟停止原因，用于用户画像分析
--   early_done  = 提前完成任务（高效信号）
--   interrupted = 临时有事被打断（噪声，排除出效率分析）
--   distracted  = 状态不好/走神（低效信号，触发 AI 干预）

ALTER TABLE pomodoros ADD COLUMN IF NOT EXISTS stop_reason VARCHAR(20) NULL;
