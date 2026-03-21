import { apiFetch } from './apiClient'

export interface MemoryItem {
  id: number
  memory_key: string
  memory_value: string
  category: string
  confidence: number
  status?: 'active' | 'ignored' | string
  is_locked?: number
  source_conversation_id?: number | null
  last_seen_at?: string | null
}

export async function listMemories(): Promise<MemoryItem[]> {
  const res = await apiFetch('/api/memory/memories')
  if (!res.ok) return []
  return res.json()
}

export async function updateMemory(
  id: number,
  data: { memory_value: string; category?: string; confidence?: number; status?: string; is_locked?: number }
): Promise<MemoryItem | null> {
  const res = await apiFetch(`/api/memory/memories/${id}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
  if (!res.ok) return null
  return res.json()
}

export async function deleteMemory(id: number): Promise<boolean> {
  const res = await apiFetch(`/api/memory/memories/${id}`, { method: 'DELETE' })
  return res.ok
}
