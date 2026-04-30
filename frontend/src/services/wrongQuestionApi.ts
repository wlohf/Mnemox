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
  knowledge_point?: string | null
  recall_difficulty?: 'easy' | 'hard' | 'forgot' | null
  mastery_score?: number | null
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
  try {
    return await apiFetch<WrongQuestionItem[]>(`/api/wrong-questions${qs ? `?${qs}` : ''}`)
  } catch {
    return []
  }
}

export async function createWrongQuestion(data: {
  content: string
  chapter_id?: number
  question_type?: string
  answer?: string
  explanation?: string
  difficulty?: number
  knowledge_point?: string
}): Promise<WrongQuestionItem | null> {
  try {
    return await apiFetch<WrongQuestionItem>('/api/wrong-questions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    })
  } catch {
    return null
  }
}

export async function updateWrongQuestion(
  id: number,
  data: {
    mastery_status?: string
    next_review_at?: string
    increment_review_count?: boolean
    recall_difficulty?: 'easy' | 'hard' | 'forgot'
  }
): Promise<WrongQuestionItem | null> {
  try {
    return await apiFetch<WrongQuestionItem>(`/api/wrong-questions/${id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    })
  } catch {
    return null
  }
}

export async function reviewWrongQuestion(
  id: number,
  quality: number,
  recall_difficulty?: 'easy' | 'hard' | 'forgot'
): Promise<WrongQuestionItem | null> {
  try {
    return await apiFetch<WrongQuestionItem>(`/api/wrong-questions/${id}/review`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ quality, recall_difficulty }),
    })
  } catch {
    return null
  }
}

export async function deleteWrongQuestion(id: number): Promise<boolean> {
  try {
    await apiFetch(`/api/wrong-questions/${id}`, { method: 'DELETE' })
    return true
  } catch {
    return false
  }
}
