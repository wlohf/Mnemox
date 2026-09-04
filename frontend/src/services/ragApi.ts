import { apiFetch } from './apiClient'
import type { RetrievalProjectionSummary } from './aiSettingsApi'

export interface RagHealth {
  enabled: boolean
  rag_online: boolean
  total_chunks: number
  embedding_enabled?: boolean
  fallback_active?: boolean
  last_retrieval_status?: {
    message?: string
    mode?: string
    ok?: boolean
  }
  message?: string
  projection_summary?: RetrievalProjectionSummary
}

export async function getRagHealth(): Promise<RagHealth> {
  return apiFetch<RagHealth>('/api/rag/health')
}
