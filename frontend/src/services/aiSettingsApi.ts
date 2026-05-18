import { apiFetch } from './apiClient'

const API_BASE = '/api/ai-settings'
export const AI_PROVIDERS_UPDATED_EVENT = 'mnemox-ai-providers-updated'

export interface AIProvidersUpdatedDetail {
  resetChatModel?: boolean
  providerName?: string
  model?: string
  availableModels?: string[]
  selectModel?: boolean
}

export function notifyAIProvidersUpdated(detail: AIProvidersUpdatedDetail = {}) {
  window.dispatchEvent(new CustomEvent(AI_PROVIDERS_UPDATED_EVENT, { detail }))
}

export interface AIProvider {
  provider_name: string
  display_name: string
  api_key_masked: string
  base_url: string
  model: string
  available_models: string[]
  is_active: boolean
  enabled: boolean
}

export interface ModelSearchResult {
  provider_name: string
  models: string[]
}

export interface ProviderUpdate {
  api_key?: string
  base_url?: string
  model?: string
  available_models?: string[]
  enabled?: boolean
}

export interface ProviderCreate {
  display_name: string
  provider_name?: string
  provider_type?: string
  api_key?: string
  base_url?: string
  model?: string
  available_models?: string[]
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
  model?: string | null
}

export async function getAllProviders(): Promise<AIProvider[]> {
  return await apiFetch<AIProvider[]>(`${API_BASE}/`)
}

export async function updateProvider(
  providerName: string,
  data: ProviderUpdate
): Promise<AIProvider> {
  return await apiFetch<AIProvider>(`${API_BASE}/${providerName}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
}

export async function createProvider(
  data: ProviderCreate
): Promise<AIProvider> {
  return await apiFetch<AIProvider>(`${API_BASE}/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
}

export async function deleteProvider(providerName: string): Promise<boolean> {
  await apiFetch(`${API_BASE}/${providerName}`, { method: 'DELETE' })
  return true
}

export async function setActiveProvider(
  providerName: string
): Promise<AIProvider> {
  return await apiFetch<AIProvider>(`${API_BASE}/active`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ provider_name: providerName }),
  })
}

export async function testProvider(
  providerName: string,
  data: { api_key?: string; base_url?: string; model?: string } = {}
): Promise<TestResult> {
  return await apiFetch<TestResult>(`${API_BASE}/test/${providerName}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
}

export async function getRoutingSettings(): Promise<AIRoutingItem[]> {
  return await apiFetch<AIRoutingItem[]>(`${API_BASE}/routing`)
}

export async function updateRoutingSetting(
  scenario: string,
  providerName?: string | null,
  model?: string | null
): Promise<AIRoutingItem> {
  return await apiFetch<AIRoutingItem>(`${API_BASE}/routing/${scenario}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ provider_name: providerName ?? null, model: model ?? null }),
  })
}

export async function searchProviderModels(
  providerName: string,
  data: { api_key?: string; base_url?: string; model_hint?: string }
): Promise<ModelSearchResult> {
  return await apiFetch<ModelSearchResult>(`${API_BASE}/${providerName}/models/search`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
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

export async function getRagSettings(): Promise<RagSettings> {
  return await apiFetch<RagSettings>('/api/rag/settings')
}

export async function updateRagSettings(
  data: RagSettingsUpdate
): Promise<{ ok: boolean; api_key_masked: string; base_url: string; model: string }> {
  return await apiFetch('/api/rag/settings', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
}

export async function testRagEmbedding(): Promise<TestResult> {
  return await apiFetch<TestResult>('/api/rag/test-embedding', { method: 'POST' })
}
