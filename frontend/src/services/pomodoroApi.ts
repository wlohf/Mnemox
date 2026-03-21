import { apiFetch } from './apiClient'

const API_BASE = '/api/pomodoro'

export interface PomodoroStartResponse {
  id: number
  chapter_id: number | null
  task_name: string | null
  started_at: string
  ended_at: string | null
  duration: number
  completed: boolean
  note: string | null
  created_at: string
}

export interface PomodoroStatsResponse {
  total_count: number
  completed_count: number
  total_minutes: number
  completion_rate: number
  avg_daily: number
}

export interface DailyStatsResponse {
  date: string
  count: number
  completed_count: number
  total_minutes: number
}

export interface BatchCreateResponse {
  created: number
  ids: number[]
}

export async function startPomodoro(
  taskName: string,
  duration: number
): Promise<PomodoroStartResponse | null> {
  try {
    const res = await apiFetch(`${API_BASE}/start`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ task_name: taskName, duration }),
    })
    if (!res.ok) return null
    return await res.json()
  } catch {
    return null
  }
}

export async function completePomodoro(
  id: number,
  completed: boolean,
  note?: string,
  actualDuration?: number,
  stopReason?: 'early_done' | 'interrupted' | 'distracted'
): Promise<PomodoroStartResponse | null> {
  try {
    const payload: { completed: boolean; note?: string; actual_duration?: number; stop_reason?: string } = { completed }
    if (note) payload.note = note
    if (actualDuration !== undefined) payload.actual_duration = actualDuration
    if (stopReason !== undefined) payload.stop_reason = stopReason
    const res = await apiFetch(`${API_BASE}/${id}/complete`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
    if (!res.ok) return null
    return await res.json()
  } catch {
    return null
  }
}

export async function getRecentPomodoros(
  limit: number = 10
): Promise<PomodoroStartResponse[] | null> {
  try {
    const res = await apiFetch(`${API_BASE}/recent?limit=${limit}`)
    if (!res.ok) return null
    return await res.json()
  } catch {
    return null
  }
}

export async function getTotalStats(): Promise<PomodoroStatsResponse | null> {
  try {
    const res = await apiFetch(`${API_BASE}/statistics/total`)
    if (!res.ok) return null
    return await res.json()
  } catch {
    return null
  }
}

export async function getWeeklyStats(): Promise<PomodoroStatsResponse | null> {
  try {
    const res = await apiFetch(`${API_BASE}/statistics/weekly`)
    if (!res.ok) return null
    return await res.json()
  } catch {
    return null
  }
}

export async function getMonthlyStats(
  year?: number,
  month?: number
): Promise<PomodoroStatsResponse | null> {
  try {
    const params = new URLSearchParams()
    if (year) params.set('year', String(year))
    if (month) params.set('month', String(month))
    const qs = params.toString()
    const res = await apiFetch(`${API_BASE}/statistics/monthly${qs ? '?' + qs : ''}`)
    if (!res.ok) return null
    return await res.json()
  } catch {
    return null
  }
}

export async function getDailyStats(
  days: number = 7
): Promise<DailyStatsResponse[] | null> {
  try {
    const res = await apiFetch(`${API_BASE}/statistics/daily?days=${days}`)
    if (!res.ok) return null
    return await res.json()
  } catch {
    return null
  }
}

export async function batchCreatePomodoros(
  records: { task_name: string; duration: number }[],
  completedAts: string[]
): Promise<BatchCreateResponse | null> {
  try {
    const res = await apiFetch(`${API_BASE}/batch`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        records: records.map((r) => ({
          task_name: r.task_name,
          duration: r.duration,
        })),
        completed_ats: completedAts,
      }),
    })
    if (!res.ok) return null
    return await res.json()
  } catch {
    return null
  }
}
