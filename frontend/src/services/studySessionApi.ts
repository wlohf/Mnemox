import { apiFetch } from './apiClient'

export interface StudySessionItem {
  id: number
  task_id?: number | null
  chapter_id?: number | null
  session_type?: string | null
  started_at?: string | null
  ended_at?: string | null
  summary?: string | null
  ai_feedback?: string | null
  created_at?: string | null
}

export async function startStudySession(taskId: number, sessionType = 'new_learning'): Promise<StudySessionItem | null> {
  const res = await apiFetch('/api/study-sessions/start', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ task_id: taskId, session_type: sessionType }),
  })
  if (!res.ok) return null
  return res.json()
}

export async function completeStudySession(
  sessionId: number,
  data?: { summary?: string; ai_feedback?: string; mark_task_completed?: boolean }
): Promise<StudySessionItem | null> {
  const res = await apiFetch(`/api/study-sessions/${sessionId}/complete`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data || {}),
  })
  if (!res.ok) return null
  return res.json()
}

export async function listTaskSessions(taskId: number): Promise<StudySessionItem[]> {
  const res = await apiFetch(`/api/study-sessions/task/${taskId}`)
  if (!res.ok) return []
  return res.json()
}

export async function listActiveStudySessions(taskId?: number): Promise<StudySessionItem[]> {
  const qs = taskId !== undefined ? `?task_id=${taskId}` : ''
  const res = await apiFetch(`/api/study-sessions/active${qs}`)
  if (!res.ok) return []
  return res.json()
}
