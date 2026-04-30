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
  try {
    return await apiFetch<ReviewTaskItem[]>(`/api/review/tasks?scope=${scope}&item_type=${itemType}`)
  } catch {
    return []
  }
}

export async function completeReviewTask(taskId: number, quality: number): Promise<ReviewTaskItem | null> {
  try {
    return await apiFetch<ReviewTaskItem>(`/api/review/tasks/${taskId}/complete`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ quality }),
    })
  } catch {
    return null
  }
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
  try {
    const data = await apiFetch<{ due_count: number }>('/api/review/due-count')
    return data.due_count ?? 0
  } catch {
    return 0
  }
}
