import { apiFetch } from './apiClient'

export type ResolutionDecision = 'pending' | 'accepted' | 'rejected' | 'create_new'
export type ResolutionAction = 'link' | 'link_add_alias' | 'create_new' | 'reject'

export interface ResolutionCandidate {
  id: number
  claim_id: number
  knowledge_unit_id: number
  mention_text: string
  mention_normalized: string
  mention_context: string
  relation_type: 'about' | 'uses' | 'applies_to' | 'exemplifies'
  candidate_concept_id?: number | null
  candidate_concept_name?: string | null
  scores: {
    exact: number
    alias: number
    lexical: number
    vector: number
    context: number
    combined: number
  }
  decision: ResolutionDecision
  resolved_concept_id?: number | null
  claim_statement?: string | null
  evidence_excerpt?: string | null
  source_type?: 'material' | 'note' | null
  source_id?: number | null
  source_title?: string | null
  created_at?: string | null
}

export async function listResolutionCandidates(options: {
  decision?: ResolutionDecision | 'all'
  sourceType?: 'material' | 'note'
  sourceId?: number
  limit?: number
} = {}): Promise<ResolutionCandidate[]> {
  const query = new URLSearchParams()
  query.set('decision', options.decision ?? 'pending')
  query.set('limit', String(options.limit ?? 100))
  if (options.sourceType) query.set('source_type', options.sourceType)
  if (options.sourceId) query.set('source_id', String(options.sourceId))
  const result = await apiFetch<{ candidates: ResolutionCandidate[] }>(
    `/api/knowledge/resolution-candidates?${query.toString()}`,
  )
  return result.candidates
}

export async function resolveKnowledgeCandidate(
  candidateId: number,
  body: {
    action: ResolutionAction
    concept_id?: number
    concept_name?: string
  },
): Promise<ResolutionCandidate> {
  return apiFetch(`/api/knowledge/resolution-candidates/${candidateId}/resolve`, {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export async function rebuildKnowledgeProjection(force = false): Promise<{
  queued: boolean
  outbox_id: number
  status: string
  embedding_enabled: boolean
}> {
  return apiFetch(`/api/knowledge/projection/rebuild?force=${force}`, { method: 'POST' })
}

