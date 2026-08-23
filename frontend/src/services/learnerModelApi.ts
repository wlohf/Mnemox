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
  review_status: 'pending' | 'confirmed' | 'rejected'
}

export interface ConceptState {
  user_id: number
  concept_id: number
  mastery_estimate: number
  confidence: number
  forgetting_risk: number
  attempt_count: number
  correct_count: number
  hint_count: number
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

export interface PrerequisiteGap {
  concept_id: number
  name: string
  mastery_estimate: number
  confidence: number
  forgetting_risk: number
  depth: number
  blocks_concept_id: number
  reason: string
}

export interface ConceptDetail {
  id: number
  name: string
  description?: string | null
  source: string
  review_status: 'pending' | 'confirmed' | 'rejected'
  aliases: Array<{ id: number; alias: string; source: string }>
  source_evidence: Array<{
    id: number
    edge_id?: number | null
    source_type: string
    source_id: number
    source_version: number
    excerpt: string
    confidence: number
    review_status: 'pending' | 'confirmed' | 'rejected'
  }>
  neighborhood: {
    nodes: Array<{ id: number; name: string; mastery: number; is_center: boolean }>
    edges: Array<{ from: number; to: number; type: string; confidence: number; review_status: string }>
    links: Array<{ concept_id: number; target_type: string; target_id: number; link_type: string }>
  }
  prerequisite_gaps: PrerequisiteGap[]
}

export interface LearningRecommendation {
  task_type: 'review_due' | 'prerequisite_gap' | 'retrieval_practice' | 'continue_goal' | 'targeted_practice'
  concept_id: number
  concept_name: string
  score: number
  score_components: Record<string, number>
  reason: string
  suggested_action: string
  estimated_minutes: number
  mastery_estimate: number
  confidence: number
  forgetting_risk: number
  goal_id?: number | null
  goal_title?: string | null
  blocked_concept_id?: number | null
  blocked_concept_name?: string | null
  evidence_ids: number[]
  review_schedule_id?: number | null
  fsrs_stability?: number | null
  next_review_at?: string | null
}

export interface LearningRecommendationPage {
  items: LearningRecommendation[]
  total: number
  generated_at: string
  model_version: string
  decision_rule?: string
}

export async function listLearnerConcepts(limit = 200): Promise<ConceptSummary[]> {
  const result = await apiFetch<{ concepts: ConceptSummary[] }>(`/api/concepts?limit=${limit}`)
  return result.concepts
}

export async function getConceptState(conceptId: number): Promise<ConceptState> {
  return apiFetch<ConceptState>(`/api/learner-model/concepts/${conceptId}/state`)
}

export async function getConceptDetail(conceptId: number): Promise<ConceptDetail> {
  return apiFetch<ConceptDetail>(`/api/concepts/${conceptId}`)
}

export async function getLearningRecommendations(limit = 10): Promise<LearningRecommendationPage> {
  return apiFetch<LearningRecommendationPage>(`/api/learner-model/recommendations?limit=${limit}`)
}

export async function addConceptAlias(conceptId: number, alias: string): Promise<{ id: number; alias: string }> {
  return apiFetch(`/api/concepts/${conceptId}/aliases`, {
    method: 'POST',
    body: JSON.stringify({ alias }),
  })
}

export async function renameConcept(conceptId: number, name: string): Promise<ConceptDetail> {
  return apiFetch(`/api/concepts/${conceptId}`, {
    method: 'PATCH',
    body: JSON.stringify({ name }),
  })
}

export async function reviewConcept(
  conceptId: number,
  reviewStatus: 'confirmed' | 'rejected',
): Promise<ConceptDetail> {
  return apiFetch(`/api/concepts/${conceptId}/review`, {
    method: 'POST',
    body: JSON.stringify({ review_status: reviewStatus }),
  })
}

export async function mergeConcept(targetConceptId: number, sourceConceptId: number): Promise<ConceptDetail> {
  return apiFetch(`/api/concepts/${targetConceptId}/merge`, {
    method: 'POST',
    body: JSON.stringify({ source_concept_id: sourceConceptId }),
  })
}

export async function deleteConcept(conceptId: number): Promise<{ deleted: boolean }> {
  return apiFetch(`/api/concepts/${conceptId}`, { method: 'DELETE' })
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
