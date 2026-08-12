import { apiFetch } from './apiClient'

export type EvidenceCategory = 'direct' | 'indirect' | 'manual' | 'legacy'

export interface ConceptSummary {
  id: number
  name: string
  description?: string | null
  mastery: number
  mastery_source: string
  mastery_model_version: string
  source: string
  link_count: number
}

export interface ConceptState {
  user_id: number
  concept_id: number
  mastery_estimate: number
  confidence: number
  forgetting_risk: number
  mastery_dimensions: Record<string, number>
  common_error_type?: string | null
  last_evidence_at?: string | null
  last_reviewed_at?: string | null
  next_review_at?: string | null
  manual_override?: {
    active?: boolean
    mastery_estimate?: number | null
    confidence?: number | null
    forgetting_risk?: number | null
    reason?: string
  } | null
  source_event_id?: number | null
  reliability: number
  model_version: string
  explanation_summary: Record<string, unknown>
  updated_at?: string | null
}

export interface LearnerEvidence {
  id: number
  user_id: number
  concept_id: number
  evidence_type: string
  evidence_category: EvidenceCategory
  dimension?: string | null
  score: number
  reliability: number
  source_event_id?: number | null
  source_type: string
  source_id?: string | null
  observed_at?: string | null
  model_version: string
  payload_version: number
  payload: Record<string, unknown>
}

export interface EvidencePage {
  items: LearnerEvidence[]
  total: number
  offset: number
  limit: number
}

export async function listLearnerConcepts(limit = 200): Promise<ConceptSummary[]> {
  const result = await apiFetch<{ concepts: ConceptSummary[] }>(`/api/concepts?limit=${limit}`)
  return result.concepts
}

export async function getConceptState(conceptId: number): Promise<ConceptState> {
  return apiFetch<ConceptState>(`/api/learner-model/concepts/${conceptId}/state`)
}

export async function getConceptEvidence(
  conceptId: number,
  options: {
    offset?: number
    limit?: number
    evidenceCategory?: EvidenceCategory
  } = {},
): Promise<EvidencePage> {
  const query = new URLSearchParams()
  query.set('offset', String(options.offset ?? 0))
  query.set('limit', String(options.limit ?? 20))
  if (options.evidenceCategory) query.set('evidence_category', options.evidenceCategory)
  return apiFetch<EvidencePage>(`/api/learner-model/concepts/${conceptId}/evidence?${query.toString()}`)
}

export async function applyConceptOverride(
  conceptId: number,
  body: {
    mastery_estimate: number
    confidence?: number
    forgetting_risk?: number
    reason: string
  },
): Promise<{ evidence: LearnerEvidence; state: ConceptState }> {
  return apiFetch(`/api/learner-model/concepts/${conceptId}/override`, {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export async function clearConceptOverride(
  conceptId: number,
  reason: string,
): Promise<{ evidence: LearnerEvidence; state: ConceptState }> {
  return apiFetch(`/api/learner-model/concepts/${conceptId}/override?reason=${encodeURIComponent(reason)}`, {
    method: 'DELETE',
  })
}

export async function recomputeConceptState(conceptId: number): Promise<ConceptState> {
  return apiFetch(`/api/learner-model/concepts/${conceptId}/recompute`, { method: 'POST' })
}
