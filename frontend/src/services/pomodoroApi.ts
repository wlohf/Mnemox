import { apiFetch } from './apiClient'
import type { ApiSessionScope } from './sessionScope'

export type StopReason = 'early_done' | 'interrupted' | 'distracted'

const API_BASE = '/api/pomodoro'

export interface PomodoroStartResponse {
  id: number
  chapter_id: number | null
  task_id: number | null
  task_name: string | null
  started_at: string
  ended_at: string | null
  duration: number
  completed: boolean
  note: string | null
  coach_action_attempt_id?: string | null
  client_record_id?: string | null
  stop_reason?: StopReason | null
  time_basis?: string
  created_at: string
}

export interface PomodoroStatsResponse {
  total_count: number
  completed_count: number
  total_minutes: number | null
  completion_rate: number | null
  avg_daily: number
}

export interface DailyStatsResponse {
  date: string
  count: number
  completed_count: number
  total_minutes: number | null
}

export interface BatchCreateResponse {
  created: number
  ids: number[]
}

export async function startPomodoro(
  taskName: string,
  duration: number,
  taskId?: number | null,
  coachActionAttemptId?: string | null,
  clientRecordId?: string,
  startedAt?: string,
  session?: ApiSessionScope,
): Promise<PomodoroStartResponse> {
  return await apiFetch<PomodoroStartResponse>(`${API_BASE}/start`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      task_name: taskName,
      duration,
      task_id: taskId ?? null,
      coach_action_attempt_id: coachActionAttemptId ?? null,
      client_record_id: clientRecordId, started_at: startedAt,
    }),
  }, session)
}

export async function completePomodoro(
  id: number,
  completed: boolean,
  note?: string,
  actualDuration?: number,
  stopReason?: 'early_done' | 'interrupted' | 'distracted'
): Promise<PomodoroStartResponse> {
  const payload: { completed: boolean; note?: string; actual_duration?: number; stop_reason?: string } = { completed }
  if (note) payload.note = note
  if (actualDuration !== undefined) payload.actual_duration = actualDuration
  if (stopReason !== undefined) payload.stop_reason = stopReason
  return await apiFetch<PomodoroStartResponse>(`${API_BASE}/${id}/complete`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

export async function getRecentPomodoros(
  limit: number = 10,
  session?: ApiSessionScope,
): Promise<PomodoroStartResponse[]> {
  return await apiFetch<PomodoroStartResponse[]>(`${API_BASE}/recent?limit=${limit}`, {}, session)
}

export async function getTotalStats(): Promise<PomodoroStatsResponse> {
  return await apiFetch<PomodoroStatsResponse>(`${API_BASE}/statistics/total`)
}

export async function getWeeklyStats(): Promise<PomodoroStatsResponse> {
  return await apiFetch<PomodoroStatsResponse>(`${API_BASE}/statistics/weekly`)
}

export async function getMonthlyStats(
  year?: number,
  month?: number
): Promise<PomodoroStatsResponse> {
  const params = new URLSearchParams()
  if (year) params.set('year', String(year))
  if (month) params.set('month', String(month))
  const qs = params.toString()
  return await apiFetch<PomodoroStatsResponse>(`${API_BASE}/statistics/monthly${qs ? '?' + qs : ''}`)
}

export async function getDailyStats(
  days: number = 7
): Promise<DailyStatsResponse[]> {
  return await apiFetch<DailyStatsResponse[]>(`${API_BASE}/statistics/daily?days=${days}`)
}

export interface PomodoroSyncRecord {
  note?: string | null
  task_name: string
  duration: number
  planned_duration?: number
  task_id?: number | null
  client_record_id: string
  backend_id?: number
  started_at?: string
  completed: boolean
  stop_reason?: StopReason | null
  coach_action_attempt_id?: string | null
}

export async function batchCreatePomodoros(
  records: PomodoroSyncRecord[],
  completedAts: string[],
  session?: ApiSessionScope,
): Promise<BatchCreateResponse> {
  return await apiFetch<BatchCreateResponse>(`${API_BASE}/batch`, {
    method: 'POST',
    body: JSON.stringify({ records, completed_ats: completedAts }),
  }, session)
}
