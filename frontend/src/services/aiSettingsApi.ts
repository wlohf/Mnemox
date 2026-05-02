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
  capability?: string
  provider_name?: string
  model?: string
}

export interface AIRoutingItem {
  scenario: string
  label: string
  provider_name?: string | null
}

export async function getAllProviders(): Promise<AIProvider[] | null> {
  try {
    return await apiFetch<AIProvider[]>(API_BASE)
  } catch {
    return null
  }
}

export async function updateProvider(
  providerName: string,
  data: ProviderUpdate
): Promise<AIProvider | null> {
  try {
    return await apiFetch<AIProvider>(`${API_BASE}/${providerName}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    })
  } catch {
    return null
  }
}

export async function createProvider(
  data: ProviderCreate
): Promise<AIProvider | null> {
  try {
    return await apiFetch<AIProvider>(API_BASE, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    })
  } catch {
    return null
  }
}

export async function deleteProvider(providerName: string): Promise<boolean> {
  try {
    await apiFetch(`${API_BASE}/${providerName}`, { method: 'DELETE' })
    return true
  } catch {
    return false
  }
}

export async function setActiveProvider(
  providerName: string
): Promise<AIProvider | null> {
  try {
    return await apiFetch<AIProvider>(`${API_BASE}/active`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ provider_name: providerName }),
    })
  } catch {
    return null
  }
}

export async function testProvider(
  providerName: string
): Promise<TestResult | null> {
  try {
    return await apiFetch<TestResult>(`${API_BASE}/test/${providerName}`, {
      method: 'POST',
    })
  } catch {
    return null
  }
}

export async function getRoutingSettings(): Promise<AIRoutingItem[] | null> {
  try {
    return await apiFetch<AIRoutingItem[]>(`${API_BASE}/routing`)
  } catch {
    return null
  }
}

export async function updateRoutingSetting(
  scenario: string,
  providerName?: string | null
): Promise<AIRoutingItem | null> {
  try {
    return await apiFetch<AIRoutingItem>(`${API_BASE}/routing/${scenario}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ provider_name: providerName ?? null }),
    })
  } catch {
    return null
  }
}

// ---- RAG Embedding Settings ----

export interface RagRetrievalStatus {
  ok?: boolean
  mode?: 'rag' | 'fallback' | 'not_run' | string
  message?: string
}

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
  embedding_enabled?: boolean
  fallback_active?: boolean
  last_error?: string
  last_retrieval_status?: RagRetrievalStatus
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
    return await apiFetch<RagSettings>('/api/rag/settings')
  } catch {
    return null
  }
}

export async function updateRagSettings(
  data: RagSettingsUpdate
): Promise<{ ok: boolean; api_key_masked: string; base_url: string; model: string } | null> {
  try {
    return await apiFetch('/api/rag/settings', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    })
  } catch {
    return null
  }
}

export async function testRagEmbedding(): Promise<TestResult | null> {
  try {
    return await apiFetch<TestResult>('/api/rag/test-embedding', { method: 'POST' })
  } catch {
    return null
  }
}
