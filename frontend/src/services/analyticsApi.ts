import { apiFetch } from './apiClient'

export interface EDAInsight {
  title: string
  detail: string
  severity: 'high' | 'medium' | 'info' | string
}

export interface EDAReport {
  period_days: number
  start_date: string
  end_date: string
  summary: {
    total_minutes: number
    avg_daily_minutes: number
    pomodoro_count: number
    completion_rate: number
    active_days: number
    total_tasks: number
    completed_tasks: number
    pending_tasks: number
    peak_hour?: number | null
    best_study_window?: string
    profile_type?: string
    profile_confidence?: number
    stop_reason_counts?: Record<string, number>
    weak_points_top?: Array<{ knowledge_point: string; wrong_count: number; mastery_status: string }>
  }
  daily_points: Array<{ date: string; study_minutes: number; pomodoro_count: number; completion_rate: number; rolling7_minutes?: number }>
  insights: EDAInsight[]
  recommendations: string[]
  profile: {
    profile_type: string
    confidence: number
    best_study_window: string
    evidence: string[]
  }
  chart_analysis: string[]
  charts: {
    daily_trend: Array<{ date: string; study_minutes: number; pomodoro_count: number; completion_rate: number; rolling7_minutes?: number }>
    hourly_distribution: Array<{ hour: number; sessions: number; minutes: number; completion_rate: number; avg_duration: number }>
    weekday_distribution: Array<{ weekday: number; label: string; sessions: number; minutes: number; completion_rate: number }>
    hour_week_heatmap: { hours: number[]; weekdays: string[]; points: Array<[number, number, number]> }
    stop_reason_distribution: Array<{ reason: string; key: string; count: number }>
    duration_bucket_distribution: Array<{ bucket: string; count: number }>
    completion_funnel: Array<{ stage: string; value: number }>
  }
  markdown: string
}

export async function getEdaReport(days = 30): Promise<EDAReport | null> {
  try {
    return await apiFetch<EDAReport>(`/api/analytics/eda-report?days=${days}`)
  } catch {
    return null
  }
}
