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
  const res = await apiFetch(`/api/motivation/current${qs ? `?${qs}` : ''}`)
  if (!res.ok) return null
  return res.json()
}

export async function listQuotes(sourceType?: string, sortMode?: string): Promise<MotivationQuote[]> {
  const query = new URLSearchParams()
  if (sourceType) query.set('source_type', sourceType)
  if (sortMode) query.set('sort_mode', sortMode)
  const qs = query.toString()
  const res = await apiFetch(`/api/motivation/quotes${qs ? `?${qs}` : ''}`)
  if (!res.ok) return []
  return res.json()
}

export async function addCustomQuote(content: string, author?: string): Promise<MotivationQuote | null> {
  const res = await apiFetch('/api/motivation/quotes', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ content, author }),
  })
  if (!res.ok) return null
  return res.json()
}

export async function deleteQuote(quoteId: number): Promise<ApiResult> {
  const res = await apiFetch(`/api/motivation/quotes/${quoteId}`, { method: 'DELETE' })
  if (res.ok) return { ok: true }
  const err = await res.json().catch(() => null)
  return { ok: false, detail: err?.detail || '删除失败' }
}

export async function generateAIQuote(): Promise<MotivationQuote | null> {
  const res = await apiFetch('/api/motivation/generate', { method: 'POST' })
  if (!res.ok) return null
  return res.json()
}

export async function getMotivationSettings(): Promise<MotivationSettings | null> {
  const res = await apiFetch('/api/motivation/settings')
  if (!res.ok) return null
  return res.json()
}

export async function updateMotivationSettings(payload: MotivationSettingsUpdate): Promise<MotivationSettings> {
  const res = await apiFetch('/api/motivation/settings', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => null)
    const detail = err?.detail || '保存失败'
    throw new Error(detail)
  }
  return res.json()
}
