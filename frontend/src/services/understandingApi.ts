import { apiFetch } from './apiClient'
export type Preferences = { analysis_enabled: boolean; graph_enabled: boolean; consume_enabled: boolean }
type Ref = { id: string; version: string; quote: string }
export type Hypothesis = {
  id: string; version: number; status: string; review_status: string; statement: string
  details: { context?: string; support?: Ref[]; counter?: Ref[]; context_refs?: Ref[]; unknowns?: string[]; next_signal?: string; user_correction?: string }
  assessment: { support_groups?: number; counter_groups?: number; unknown_groups?: number; reason?: string; interval_95?: number[]; interval_meaning?: string }
}
export type Usage = { model_calls: number; usage_missing_calls: number; reported_tokens: number; actual_tokens: number | null; reserved_tokens: number; configured_cost_usd: number | null }
type Job = { id: string; status: string; task: string; scheduled_for?: string; usage?: Usage; result?: { error?: string; abstention_reason?: string }; calls: { category: string; state: string; usage?: { total_tokens?: number; configured_cost_usd?: number | null } }[] }
export type Experience = { id: string; version: string; source: string; kind: string; text?: string; note?: string; suggestion?: string; outcome?: string; local_date?: string; occurred_at?: string; recorded_at?: string; retrieved_by?: string; match_kind?: string; graph?: { eligible: boolean; saved: boolean; extraction_revision: number } }
export type MemoryRecall = { backend: string; reason: string; graph_scope_truncated?: boolean; experiences: Experience[]; timeline: { id: string }[]; connections: { from_id: string; to_id: string; entity: string }[] }
export type Overview = { preferences: Preferences; capabilities: { graphiti_episodes: boolean }; evidence_count: number; hypotheses: Hypothesis[]; jobs: Job[]; daily_usage?: Usage & { date_utc: string; call_limit: number; token_limit: number }; graph_projection?: { eligible: number; saved: number; pending: number } }

export const getUnderstanding = () => apiFetch<Overview>('/api/understanding')
export const setUnderstandingPreferences = (preferences: Preferences) => apiFetch('/api/understanding/preferences', { method: 'PUT', body: JSON.stringify(preferences) })
export const refreshUnderstanding = () => apiFetch('/api/understanding/refresh', { method: 'POST' })
export const analyzeUnderstanding = () => apiFetch('/api/understanding/analyze', { method: 'POST', body: JSON.stringify({ request_id: crypto.randomUUID() }) })
export const reviewUnderstanding = (h: Hypothesis, action: string, correction: string | null) => apiFetch(`/api/understanding/hypotheses/${h.id}/review`, { method: 'POST', body: JSON.stringify({ version: h.version, action, correction }) })
export const getUnderstandingEvidence = (id: string) => apiFetch(`/api/understanding/evidence/${id}`)
export const getUnderstandingHistory = (id: string) => apiFetch(`/api/understanding/hypotheses/${id}/history`)
export const searchUnderstandingMemory = (query: string) => apiFetch<MemoryRecall>(`/api/understanding/memory?q=${encodeURIComponent(query)}`)
export const rebuildUnderstandingGraph = () => apiFetch('/api/understanding/graph/rebuild', { method: 'POST', body: JSON.stringify({ request_id: crypto.randomUUID() }) })
export const excludeUnderstandingEvidence = (id: string) => apiFetch(`/api/understanding/evidence/${id}`, { method: 'DELETE' })
export const retryUnderstandingJob = (id: string) => apiFetch(`/api/understanding/jobs/${id}/retry`, { method: 'POST', body: JSON.stringify({ request_id: crypto.randomUUID() }) })
export const reextractUnderstandingEvidence = (record: Experience) => apiFetch(`/api/understanding/graph/reextract?experience_id=${encodeURIComponent(record.id)}`, { method: 'POST', body: JSON.stringify({ request_id: crypto.randomUUID(), experience_version: record.version }) })
export const cleanupUnderstandingGraph = () => apiFetch('/api/understanding/graph/cleanup', { method: 'POST', body: JSON.stringify({ request_id: crypto.randomUUID() }) })
