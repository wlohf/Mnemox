import { apiFetch } from './apiClient'

export interface DailyInterventionReport {
  date: string
  risk_level: 'low' | 'medium' | 'high'
  should_push: boolean
  summary: string
  push_title: string
  push_body: string
  highlights: string[]
  suggestions: string[]
  stats: {
    today_minutes: number
    pomodoro_count: number
    total_tasks: number
    completed_tasks: number
    pending_tasks: number
    due_review_count: number
    completion_rate: number
  }
}

export async function getDailyIntervention(daysOffset = 0): Promise<DailyInterventionReport | null> {
  try {
    return await apiFetch<DailyInterventionReport>(`/api/interventions/daily?days_offset=${daysOffset}`)
  } catch {
    return null
  }
}

export async function generateDailyIntervention(): Promise<DailyInterventionReport | null> {
  try {
    return await apiFetch<DailyInterventionReport>('/api/interventions/daily/generate', { method: 'POST' })
  } catch {
    return null
  }
}
