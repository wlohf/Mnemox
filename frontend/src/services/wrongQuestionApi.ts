import { apiFetch } from './apiClient'

export interface WrongQuestionItem {
  id: number
  question_id: number
  content: string
  question_type?: string | null
  answer?: string | null
  explanation?: string | null
  difficulty?: number | null
  chapter_id?: number | null
  chapter_title: string
  wrong_count: number
  mastery_status: 'not_mastered' | 'partial' | 'mastered'
  review_count: number
  next_review_at?: string | null
  last_wrong_at?: string | null
  created_at?: string | null
}

export async function listWrongQuestions(params?: {
  mastery_status?: string
  due_only?: boolean
}): Promise<WrongQuestionItem[]> {
  const query = new URLSearchParams()
  if (params?.mastery_status) query.set('mastery_status', params.mastery_status)
  if (params?.due_only) query.set('due_only', 'true')
  const qs = query.toString()
  const res = await apiFetch(`/api/wrong-questions${qs ? `?${qs}` : ''}`)
  if (!res.ok) return []
  return res.json()
}

export async function createWrongQuestion(data: {
  content: string
  chapter_id?: number
  question_type?: string
  answer?: string
  explanation?: string
  difficulty?: number
}): Promise<WrongQuestionItem | null> {
  const res = await apiFetch('/api/wrong-questions', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
  if (!res.ok) return null
  return res.json()
}

export async function updateWrongQuestion(
  id: number,
  data: { mastery_status?: string; next_review_at?: string; increment_review_count?: boolean }
): Promise<WrongQuestionItem | null> {
  const res = await apiFetch(`/api/wrong-questions/${id}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
  if (!res.ok) return null
  return res.json()
}

export async function reviewWrongQuestion(id: number, quality: number): Promise<WrongQuestionItem | null> {
  const res = await apiFetch(`/api/wrong-questions/${id}/review`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ quality }),
  })
  if (!res.ok) return null
  return res.json()
}

export async function deleteWrongQuestion(id: number): Promise<boolean> {
  const res = await apiFetch(`/api/wrong-questions/${id}`, { method: 'DELETE' })
  return res.ok
}
