import { apiFetch } from './apiClient'

export interface AssociationEvidence {
  id: number
  title?: string
  route?: string
  knowledge_point?: string
  mastery_status?: string
  wrong_count?: number
  updated_at?: string | null
}

export interface ConceptAssociation {
  concept_id: number
  concept_name: string
  mastery: number
  mastery_source: string
  reason: string
  score: number
  evidence: {
    notes: AssociationEvidence[]
    wrong_questions: AssociationEvidence[]
  }
  prerequisites: Array<{
    concept_id: number
    name: string
    evidence: {
      notes: AssociationEvidence[]
      wrong_questions: AssociationEvidence[]
    }
  }>
  related_concepts: Array<{ concept_id: number; name: string }>
}

export interface AssociationRecallNudge {
  id: string
  skill_id: string
  title: string
  body: string
  status: string
  suggested_action?: {
    label?: string
    route?: string
    [key: string]: unknown
  }
  explainability?: Record<string, unknown> | null
}

export interface AssociationRecallResponse {
  associations: ConceptAssociation[]
  event: {
    id: string
    event_type: string
    dedupe_key?: string | null
  } | null
  nudge: AssociationRecallNudge | null
}

export async function findConceptAssociations(
  text: string,
  limit = 3,
): Promise<AssociationRecallResponse> {
  return apiFetch<AssociationRecallResponse>('/api/concepts/associate', {
    method: 'POST',
    body: JSON.stringify({
      text,
      limit,
    }),
  })
}
