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
  const res = await apiFetch(`/api/review/tasks?scope=${scope}&item_type=${itemType}`)
  if (!res.ok) return []
  return res.json()
}

export async function completeReviewTask(taskId: number, quality: number): Promise<ReviewTaskItem | null> {
  const res = await apiFetch(`/api/review/tasks/${taskId}/complete`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ quality }),
  })
  if (!res.ok) return null
  return res.json()
}

export async function getDueReviewCount(): Promise<number> {
  try {
    const res = await apiFetch('/api/review/due-count')
    if (!res.ok) return 0
    const data = await res.json()
    return data.due_count ?? 0
  } catch {
    return 0
  }
}
