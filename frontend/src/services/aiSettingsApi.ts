import { apiFetch } from './apiClient'

const API_BASE = '/api/ai-settings'
export const AI_PROVIDERS_UPDATED_EVENT = 'mnemox-ai-providers-updated'
const WEB_SEARCH_MODE_KEY = 'chat_web_search_mode'
const WEB_SEARCH_PROVIDER_KEY = 'chat_web_search_provider'

export type WebSearchMode = 'auto' | 'provider_hosted' | 'app_search' | 'grok_summary' | 'tavily' | 'local_fallback'
export const DEFAULT_WEB_SEARCH_MODE: WebSearchMode = 'auto'

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
  max_context_tokens?: number | null
  max_output_tokens?: number | null
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
  max_context_tokens?: number | null
  max_output_tokens?: number | null
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
  max_context_tokens?: number | null
  max_output_tokens?: number | null
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

export interface SearchSettings {
  enabled: boolean
  default_mode: WebSearchMode
  provider: 'auto' | 'tavily' | 'local_fallback'
  tavily_api_key_masked: string
  tavily_search_depth: 'basic' | 'advanced'
  tavily_max_results: number
  tavily_chunks_per_source: number
  tavily_include_answer: boolean
  tavily_include_raw_content: boolean
  timeout_seconds: number
  fallback_enabled: boolean
  updated_at?: string | null
}

export interface SearchSettingsUpdate {
  enabled?: boolean
  default_mode?: WebSearchMode
  provider?: 'auto' | 'tavily' | 'local_fallback'
  tavily_api_key?: string
  tavily_search_depth?: 'basic' | 'advanced'
  tavily_max_results?: number
  tavily_chunks_per_source?: number
  tavily_include_answer?: boolean
  tavily_include_raw_content?: boolean
  timeout_seconds?: number
  fallback_enabled?: boolean
}

export interface SearchTestResult {
  success: boolean
  message: string
  provider: string
  result_count: number
}

export function normalizeWebSearchMode(value?: string | null): WebSearchMode {
  switch ((value || '').trim()) {
    case 'provider_hosted':
    case 'app_search':
    case 'grok_summary':
    case 'tavily':
    case 'local_fallback':
      return value as WebSearchMode
    default:
      return DEFAULT_WEB_SEARCH_MODE
  }
}

export function getStoredWebSearchMode(): WebSearchMode {
  return normalizeWebSearchMode(localStorage.getItem(WEB_SEARCH_MODE_KEY))
}

export function setStoredWebSearchMode(mode: WebSearchMode) {
  localStorage.setItem(WEB_SEARCH_MODE_KEY, normalizeWebSearchMode(mode))
}

export function getStoredWebSearchProviderName(): string {
  return (localStorage.getItem(WEB_SEARCH_PROVIDER_KEY) || '').trim()
}

export function setStoredWebSearchProviderName(providerName?: string | null) {
  const value = (providerName || '').trim()
  if (value) {
    localStorage.setItem(WEB_SEARCH_PROVIDER_KEY, value)
    return
  }
  localStorage.removeItem(WEB_SEARCH_PROVIDER_KEY)
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

export async function getSearchSettings(): Promise<SearchSettings> {
  return await apiFetch<SearchSettings>(`${API_BASE}/search`)
}

export async function updateSearchSettings(data: SearchSettingsUpdate): Promise<SearchSettings> {
  return await apiFetch<SearchSettings>(`${API_BASE}/search`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
}

export async function testSearchSettings(data: { query?: string; tavily_api_key?: string } = {}): Promise<SearchTestResult> {
  return await apiFetch<SearchTestResult>(`${API_BASE}/search/test`, {
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
