import { apiFetch } from './apiClient'

export interface MemoryItem {
  id: number
  memory_key: string
  memory_value: string
  category: string
  confidence: number
  status?: 'active' | 'staged' | 'ignored' | 'superseded' | 'expired' | string
  is_locked?: number
  source_conversation_id?: number | null
  source_type?: string | null
  source_id?: string | number | null
  evidence?: unknown
  expires_at?: string | null
  review_status?: 'staged' | 'confirmed' | 'ignored' | 'inaccurate' | 'superseded' | 'expired' | string | null
  memory_type?: string | null
  material_id?: number | null
  last_seen_at?: string | null
  fact_key?: string
  conflicts_with_id?: number | null
  resolution_reason?: string | null
  valid_from?: string | null
  valid_to?: string | null
}

export interface MemoryDeclaration {
  id: number
  memory_id: number
  subject: string
  predicate: string
  fact_key: string
  value: string
  valid_from: string | null
  valid_to: string | null
  observed_at: string | null
  confidence: number
  review_status: 'staged' | 'confirmed' | 'superseded' | 'ignored' | 'inaccurate' | 'expired' | string
  source_event_id: number | null
  source_type: string
  source_id: string | null
  evidence: unknown
  created_by: string
  model_version: string | null
  supersedes_id: number | null
  conflicts_with_id: number | null
  resolution_reason: string | null
  created_at: string | null
}

export interface MemoryConflict {
  fact_key: string
  candidate_memory_id: number
  current_memory_id: number
  candidate: MemoryDeclaration
  current: MemoryDeclaration
}

export async function createMemory(data: {
  memory_key: string
  memory_value: string
  category?: string
  confidence?: number
  expires_at?: string | null
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

export async function listMemoryConflicts(): Promise<MemoryConflict[]> {
  try {
    return await apiFetch<MemoryConflict[]>('/api/memory/conflicts')
  } catch {
    return []
  }
}

export async function updateMemory(
  id: number,
  data: {
    memory_value: string
    category?: string
    confidence?: number
    status?: string
    is_locked?: number
    expires_at?: string | null
    correction_reason?: string
  }
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

export async function correctMemory(
  id: number,
  data: {
    memory_value: string
    reason: string
    category?: string
    confidence?: number
    expires_at?: string | null
  },
): Promise<MemoryItem | null> {
  try {
    return await apiFetch<MemoryItem>(`/api/memory/memories/${id}/correct`, {
      method: 'POST',
      body: JSON.stringify(data),
    })
  } catch {
    return null
  }
}

export async function reviewMemoryCandidate(
  id: number,
  decision: 'confirm' | 'ignore' | 'inaccurate',
  lock = false,
): Promise<MemoryItem | null> {
  const action = decision === 'confirm' ? 'confirm' : 'ignore'
  const payload = decision === 'confirm' ? { lock } : { reason: decision }
  try {
    return await apiFetch<MemoryItem>(`/api/agent/memory/candidates/${id}/${action}`, {
      method: 'POST',
      body: JSON.stringify(payload),
    })
  } catch {
    return null
  }
}

export async function expireMemories(): Promise<{ expired_count: number; memory_ids: number[] } | null> {
  try {
    return await apiFetch<{ expired_count: number; memory_ids: number[] }>('/api/memory/expire', {
      method: 'POST',
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
