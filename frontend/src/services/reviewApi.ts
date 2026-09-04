import { apiFetch } from './apiClient'

export interface ReviewTaskItem {
  task_id: number
  item_type: 'question' | 'chapter' | string
  item_id: number
  scheduled_date?: string | null
  interval_days?: number | null
  ease_factor?: number | null
  repetitions?: number | null
  status?: string | null
  content: string
  chapter_title: string
  mastery_status: 'not_mastered' | 'partial' | 'mastered'
  wrong_count: number
  review_count: number
  chapter_mastery_level?: number | null
  last_wrong_at?: string | null
  next_review_at?: string | null
}

export async function listReviewTasks(
  scope: 'due' | 'all' = 'due',
  itemType: 'all' | 'question' | 'chapter' = 'all'
): Promise<ReviewTaskItem[]> {
  return await apiFetch<ReviewTaskItem[]>(`/api/review/tasks?scope=${scope}&item_type=${itemType}`)
}

export async function completeReviewTask(
  taskId: number,
  quality: number,
  coachActionAttemptId?: string | null,
): Promise<ReviewTaskItem | null> {
  return await apiFetch<ReviewTaskItem>(`/api/review/tasks/${taskId}/complete`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ quality, coach_action_attempt_id: coachActionAttemptId ?? null }),
  })
}

export async function deleteReviewTask(taskId: number): Promise<boolean> {
  try {
    await apiFetch(`/api/review/tasks/${taskId}`, { method: 'DELETE' })
    return true
  } catch {
    return false
  }
}

export async function getDueReviewCount(): Promise<number> {
  const data = await apiFetch<{ due_count: number }>('/api/review/due-count')
  return data.due_count ?? 0
}

export interface ReviewContent {
  summary: string[]
  questions: Array<{
    id: number
    type: 'choice' | 'short_answer'
    question: string
    options?: string[]
    correct_answer?: string
    reference_answer?: string
  }>
}

export interface ReviewResult {
  score: number
  quality: number
  feedback: string
  next_review_date: string
}

export async function getReviewContent(taskId: number): Promise<ReviewContent> {
  return apiFetch<ReviewContent>(`/api/review/${taskId}/content`)
}

export async function submitReviewAnswers(
  taskId: number,
  data: { answers: Array<{ question: string; answer: string }>; coach_action_attempt_id?: string | null },
): Promise<ReviewResult> {
  return apiFetch<ReviewResult>(`/api/review/${taskId}/submit`, {
    method: 'POST',
    body: JSON.stringify(data),
  })
}
