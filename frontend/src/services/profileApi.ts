import { apiFetch } from './apiClient'

export interface FocusEvidenceMetrics {
  finished_count: number
  completed_count: number
  completion_rate: number | null
  actual_minutes: number | null
  actual_duration_count: number
  unknown_actual_duration_count: number
  median_actual_minutes: number | null
  hour_counts: Record<string, number>
}

export interface FocusEvidenceSummary {
  assessment: 'descriptive_only'
  time_zone: string
  time_zone_source: string
  metrics: FocusEvidenceMetrics
  coverage: {
    included_record_count: number
    excluded_record_count: number
    excluded_all_time_count?: number
    observed_days: number
    unlinked_task_count: number
    truncated: boolean
  }
  quality_counts: Record<string, number>
  limitations: string[]
}

export interface UserProfile {
  user_id: number
  total_study_hours: number
  total_study_days: number
  total_pomodoros: number
  avg_session_duration: number
  avg_pomodoro_per_day: number
  optimal_hours: string | null
  preferred_time_slots: Record<string, number> | null
  self_control_score: number
  consistency_score: number
  focus_score: number
  planning_score: number
  streak_days: number
  weak_points: string[] | null
  recent_performance: Record<string, unknown> | null
  last_updated: string | null
  data_insufficient: boolean
  insights: string[]
  evidence_summary?: FocusEvidenceSummary | null
  lifetime_metrics?: FocusEvidenceMetrics | null
}

export async function getProfile(): Promise<UserProfile | null> {
  try {
    return await apiFetch<UserProfile>('/api/profile')
  } catch {
    return null
  }
}

export async function refreshProfile(): Promise<UserProfile | null> {
  try {
    return await apiFetch<UserProfile>('/api/profile/refresh', { method: 'POST' })
  } catch {
    return null
  }
}
