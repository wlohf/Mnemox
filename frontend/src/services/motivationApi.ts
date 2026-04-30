import { apiFetch } from './apiClient'

export interface MotivationQuote {
  id: number
  content: string
  author: string | null
  source_type: 'preset' | 'custom' | 'ai' | string
  created_at: string | null
}

export interface MotivationSettings {
  display_mode: 'auto' | 'manual'
  selected_quote_id: number | null
  sort_mode: 'created_desc' | 'created_asc' | 'source_priority' | 'author_asc' | 'content_asc' | string
  rotation_seconds: number
}

export interface MotivationSettingsUpdate {
  display_mode?: 'auto' | 'manual'
  selected_quote_id?: number
  sort_mode?: 'created_desc' | 'created_asc' | 'source_priority' | 'author_asc' | 'content_asc' | string
  rotation_seconds?: number
}

export interface ApiResult {
  ok: boolean
  detail?: string
}

export async function getCurrentQuote(refresh?: number): Promise<MotivationQuote | null> {
  const query = new URLSearchParams()
  if (refresh !== undefined) query.set('refresh', String(refresh))
  const qs = query.toString()
  try {
    return await apiFetch<MotivationQuote>(`/api/motivation/current${qs ? `?${qs}` : ''}`)
  } catch {
    return null
  }
}

export async function listQuotes(sourceType?: string, sortMode?: string): Promise<MotivationQuote[]> {
  const query = new URLSearchParams()
  if (sourceType) query.set('source_type', sourceType)
  if (sortMode) query.set('sort_mode', sortMode)
  const qs = query.toString()
  try {
    return await apiFetch<MotivationQuote[]>(`/api/motivation/quotes${qs ? `?${qs}` : ''}`)
  } catch {
    return []
  }
}

export async function addCustomQuote(content: string, author?: string): Promise<MotivationQuote | null> {
  try {
    return await apiFetch<MotivationQuote>('/api/motivation/quotes', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content, author }),
    })
  } catch {
    return null
  }
}

export async function deleteQuote(quoteId: number): Promise<ApiResult> {
  try {
    await apiFetch(`/api/motivation/quotes/${quoteId}`, { method: 'DELETE' })
    return { ok: true }
  } catch (e: any) {
    return { ok: false, detail: e?.message || '删除失败' }
  }
}

export async function generateAIQuote(): Promise<MotivationQuote | null> {
  try {
    return await apiFetch<MotivationQuote>('/api/motivation/generate', { method: 'POST' })
  } catch {
    return null
  }
}

export async function getMotivationSettings(): Promise<MotivationSettings | null> {
  try {
    return await apiFetch<MotivationSettings>('/api/motivation/settings')
  } catch {
    return null
  }
}

export async function updateMotivationSettings(payload: MotivationSettingsUpdate): Promise<MotivationSettings> {
  return apiFetch<MotivationSettings>('/api/motivation/settings', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}
