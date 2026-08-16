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
  source_type?: string | null
  source_id?: string | number | null
  evidence?: unknown
  expires_at?: string | null
  review_status?: 'staged' | 'confirmed' | 'ignored' | 'inaccurate' | string | null
  memory_type?: string | null
  material_id?: number | null
  last_seen_at?: string | null
}

export interface MemoryDeclaration {
  id: number
  memory_id: number
  subject: string
  predicate: string
  value: string
  valid_from: string | null
  valid_to: string | null
  observed_at: string | null
  confidence: number
  review_status: 'confirmed' | 'superseded' | 'ignored' | string
  source_event_id: number | null
  source_type: string
  source_id: string | null
  evidence: unknown
  created_by: string
  model_version: string | null
  supersedes_id: number | null
  created_at: string | null
}

export async function createMemory(data: {
  memory_key: string
  memory_value: string
  category?: string
  confidence?: number
}): Promise<MemoryItem | null> {
  try {
    return await apiFetch<MemoryItem>('/api/memory/memories', {
      method: 'POST',
      body: JSON.stringify(data),
    })
  } catch {
    return null
  }
}


export async function listMemories(): Promise<MemoryItem[]> {
  try {
    return await apiFetch<MemoryItem[]>('/api/memory/memories')
  } catch {
    return []
  }
}

export async function listMemoryDeclarations(id: number): Promise<MemoryDeclaration[]> {
  try {
    return await apiFetch<MemoryDeclaration[]>(`/api/memory/memories/${id}/declarations`)
  } catch {
    return []
  }
}

export async function updateMemory(
  id: number,
  data: { memory_value: string; category?: string; confidence?: number; status?: string; is_locked?: number }
): Promise<MemoryItem | null> {
  try {
    return await apiFetch<MemoryItem>(`/api/memory/memories/${id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    })
  } catch {
    return null
  }
}

export async function deleteMemory(id: number): Promise<boolean> {
  try {
    await apiFetch(`/api/memory/memories/${id}`, { method: 'DELETE' })
    return true
  } catch {
    return false
  }
}
