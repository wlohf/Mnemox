import { apiFetch } from './apiClient'

const API_BASE = '/api/ai-settings/'

export interface AIProvider {
  provider_name: string
  display_name: string
  api_key_masked: string
  base_url: string
  model: string
  is_active: boolean
  enabled: boolean
}

export interface ProviderUpdate {
  api_key?: string
  base_url?: string
  model?: string
  enabled?: boolean
}

export interface ProviderCreate {
  display_name: string
  provider_name?: string
  provider_type?: string
  api_key?: string
  base_url?: string
  model?: string
  enabled?: boolean
}

export interface TestResult {
  success: boolean
  message: string
}

export interface AIRoutingItem {
  scenario: string
  label: string
  provider_name?: string | null
}

export async function getAllProviders(): Promise<AIProvider[] | null> {
  try {
    const res = await apiFetch(API_BASE)
    if (!res.ok) return null
    return await res.json()
  } catch {
    return null
  }
}

export async function updateProvider(
  providerName: string,
  data: ProviderUpdate
): Promise<AIProvider | null> {
  try {
    const res = await apiFetch(`${API_BASE}/${providerName}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    })
    if (!res.ok) return null
    return await res.json()
  } catch {
    return null
  }
}

export async function createProvider(
  data: ProviderCreate
): Promise<AIProvider | null> {
  try {
    const res = await apiFetch(API_BASE, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    })
    if (!res.ok) return null
    return await res.json()
  } catch {
    return null
  }
}

export async function deleteProvider(providerName: string): Promise<boolean> {
  try {
    const res = await apiFetch(`${API_BASE}/${providerName}`, {
      method: 'DELETE',
    })
    return res.ok
  } catch {
    return false
  }
}

export async function setActiveProvider(
  providerName: string
): Promise<AIProvider | null> {
  try {
    const res = await apiFetch(`${API_BASE}/active`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ provider_name: providerName }),
    })
    if (!res.ok) return null
    return await res.json()
  } catch {
    return null
  }
}

export async function testProvider(
  providerName: string
): Promise<TestResult | null> {
  try {
    const res = await apiFetch(`${API_BASE}/test/${providerName}`, {
      method: 'POST',
    })
    if (!res.ok) return null
    return await res.json()
  } catch {
    return null
  }
}

export async function getRoutingSettings(): Promise<AIRoutingItem[] | null> {
  try {
    const res = await apiFetch(`${API_BASE}/routing`)
    if (!res.ok) return null
    return await res.json()
  } catch {
    return null
  }
}

export async function updateRoutingSetting(
  scenario: string,
  providerName?: string | null
): Promise<AIRoutingItem | null> {
  try {
    const res = await apiFetch(`${API_BASE}/routing/${scenario}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ provider_name: providerName ?? null }),
    })
    if (!res.ok) return null
    return await res.json()
  } catch {
    return null
  }
}

// ---- RAG Embedding Settings ----

export interface RagSettings {
  api_key_masked: string
  base_url: string
  model: string
  initialized: boolean
  total_chunks: number
  chunk_size: number
  chunk_overlap: number
  top_k: number
  similarity_threshold: number
}

export interface RagSettingsUpdate {
  api_key?: string
  base_url?: string
  model?: string
  chunk_size?: number
  chunk_overlap?: number
  top_k?: number
  similarity_threshold?: number
}

export async function getRagSettings(): Promise<RagSettings | null> {
  try {
    const res = await apiFetch('/api/rag/settings')
    if (!res.ok) return null
    return await res.json()
  } catch {
    return null
  }
}

export async function updateRagSettings(
  data: RagSettingsUpdate
): Promise<{ ok: boolean; api_key_masked: string; base_url: string; model: string } | null> {
  try {
    const res = await apiFetch('/api/rag/settings', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    })
    if (!res.ok) return null
    return await res.json()
  } catch {
    return null
  }
}

export async function testRagEmbedding(): Promise<TestResult | null> {
  try {
    const res = await apiFetch('/api/rag/test-embedding', {
      method: 'POST',
    })
    if (!res.ok) return null
    return await res.json()
  } catch {
    return null
  }
}
