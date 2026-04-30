import { apiFetch } from './apiClient'

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
