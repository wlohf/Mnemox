import { apiFetch } from './apiClient'

export interface KnowledgeLabMaterial {
  id: number
  title: string
  file_type?: string | null
  created_at?: string
  content_status?: string | null
  knowledge_extraction?: Record<string, unknown> | null
}

export interface KnowledgeLabStatus {
  enabled: boolean
  semantic_auto_resolve_enabled: boolean
  counts: {
    sources: number
    claims: number
    confirmed_claim_links: number
    resolution_candidates: number
    pending_resolution: number
  }
  projection?: Record<string, any> | null
  graph_runtime?: {
    selected_backend?: string
    configured_backend?: string
    effective_backend?: string
    primary_ready?: boolean
    serving_ready?: boolean
    neo4j_read_enabled?: boolean
    rollout?: Record<string, any> | null
    projection?: Record<string, any> | null
    health?: Record<string, any> | null
  } | null
}

export interface ExtractionRun {
  id: number
  source_revision_id?: number
  extractor_type: string
  status: string
  attempt_count?: number
  provider?: string | null
  model?: string | null
  stats?: Record<string, any>
  usage?: Record<string, any>
  created_at?: string | null
  updated_at?: string | null
  started_at?: string | null
  finished_at?: string | null
  last_error?: string | null
}

export interface MaterialExtractionSummary {
  enabled: boolean
  llm_enabled: boolean
  source_revision_id?: number | null
  status: string
  deterministic_status?: string
  llm_status?: string
  pending_claim_count?: number
  pending_resolution_count?: number
  runs?: ExtractionRun[]
}

export interface LabEvidence {
  id: number
  excerpt: string
  confidence: number
  grounding_method: string
  locator: Record<string, any>
  unit: {
    id: number
    type: string
    ordinal: number
  }
}

export interface LabClaimConcept {
  link_id: number
  concept_id: number
  name: string
  relation_type: string
  confidence: number
  review_status: string
}

export interface LabClaim {
  id: number
  statement: string
  claim_kind: string
  confidence: number
  derivation_type: string
  review_status: 'pending' | 'confirmed' | 'rejected'
  reviewed_at?: string | null
  evidence: LabEvidence[]
  concepts: LabClaimConcept[]
}

export interface MaterialClaimSnapshot {
  material: {
    id: number
    title: string
    file_type: string
  }
  source: {
    registered: boolean
    source_id?: number | null
    current_revision: number
    revision_id?: number
    revision?: number
    title?: string
  }
  counts: {
    total: number
    pending: number
    confirmed: number
    rejected: number
  }
  claims: LabClaim[]
  truncated: boolean
}

export interface LabConcept {
  id: number
  name: string
  description?: string | null
  mastery: number
  mastery_source?: string
  review_status: string
  source?: string
  link_count: number
}

export interface AssociationExplanation {
  kind: string
  summary: string
  steps: Array<Record<string, any>>
  evidence: Array<{
    source_type: string
    source_id: number
    source_version: number
    excerpt: string
    confidence: number
  }>
}

export interface AssociationItem {
  anchor: {
    claim: string
    claim_ids: number[]
    concepts: Array<{ id: number; name: string }>
  }
  related: {
    claim_id: number
    claim: string
    source_type: string
    source_id: number
    source_title: string
  }
  relation: string
  shared_structure: string
  important_difference: string
  evidence: {
    anchor: Array<Record<string, any>>
    related: Array<{
      id: number
      evidence_key: string
      excerpt: string
      locator: Record<string, any>
      confidence: number
    }>
  }
  score: number
  confidence: number
  inferred: boolean
  explanation?: AssociationExplanation | null
  scores?: Record<string, number>
}

export interface AssociationResponse {
  associations: AssociationItem[]
  diagnostics: Record<string, any>
}

export interface KnowledgePathNode {
  concept_id: number
  name: string
  description?: string | null
  learning_status: 'mastered' | 'weak' | 'unseen' | string
  mastery_estimate: number
  confidence: number
  forgetting_risk: number
  reliability?: number
  learner_evidence?: Record<string, any>
  is_start: boolean
  is_target: boolean
}

export interface KnowledgePathEdge {
  relation_type: string
  from: { concept_id: number; name: string }
  to: { concept_id: number; name: string }
  directed: boolean
  traversed_forward: boolean
  confidence: number
  source: string
  provenance_status: string
  evidence: Array<{
    source_type: string
    source_id: number
    source_version: number
    excerpt: string
    confidence: number
  }>
}

export interface KnowledgePathResponse {
  status: 'ok' | 'no_path' | string
  target: { concept_id: number; name: string }
  paths: Array<{
    depth: number
    score: number
    nodes: KnowledgePathNode[]
    edges: KnowledgePathEdge[]
  }>
  runtime: Record<string, any>
}

export async function listLabMaterials(): Promise<KnowledgeLabMaterial[]> {
  return apiFetch<KnowledgeLabMaterial[]>('/api/materials/?skip=0&limit=100')
}

export async function uploadLabMaterial(file: File): Promise<KnowledgeLabMaterial & { duplicate?: boolean }> {
  const form = new FormData()
  form.append('file', file)
  form.append('title', file.name)
  form.append('sync_to_rag', 'true')
  return apiFetch('/api/materials/upload', {
    method: 'POST',
    body: form,
  })
}

export async function getKnowledgeLabStatus(): Promise<KnowledgeLabStatus> {
  return apiFetch('/api/knowledge/status')
}

export async function getMaterialExtraction(materialId: number): Promise<MaterialExtractionSummary> {
  return apiFetch(`/api/knowledge/materials/${materialId}/extraction`)
}

export async function startMaterialExtraction(materialId: number): Promise<ExtractionRun> {
  return apiFetch(`/api/knowledge/materials/${materialId}/extract`, { method: 'POST' })
}

export async function getExtractionRun(runId: number): Promise<ExtractionRun> {
  return apiFetch(`/api/knowledge/extraction-runs/${runId}`)
}

export async function getMaterialClaims(
  materialId: number,
  reviewStatus: 'all' | 'pending' | 'confirmed' | 'rejected' = 'all',
): Promise<MaterialClaimSnapshot> {
  return apiFetch(
    `/api/knowledge/materials/${materialId}/claims?review_status=${reviewStatus}&limit=300`,
  )
}

export async function reviewLabClaim(
  claimId: number,
  reviewStatus: 'confirmed' | 'rejected',
): Promise<{ id: number; review_status: string; reviewed_at?: string | null }> {
  return apiFetch(`/api/knowledge/claims/${claimId}/review`, {
    method: 'POST',
    body: JSON.stringify({ review_status: reviewStatus }),
  })
}

export async function listLabConcepts(): Promise<LabConcept[]> {
  const result = await apiFetch<{ concepts: LabConcept[] }>('/api/concepts?limit=500')
  return result.concepts
}

export async function runLabAssociation(body: {
  text: string
  source_type?: 'material' | 'note'
  source_id?: number
  limit?: number
}): Promise<AssociationResponse> {
  return apiFetch('/api/knowledge/associate', {
    method: 'POST',
    body: JSON.stringify({ ...body, limit: body.limit ?? 5 }),
  })
}

export async function runLabKnowledgePath(body: {
  start_concept_ids: number[]
  target_concept_id: number
  max_depth?: number
  relation_types?: Array<'prerequisite_of' | 'related_to'>
  limit?: number
}): Promise<KnowledgePathResponse> {
  return apiFetch('/api/knowledge/learning-path', {
    method: 'POST',
    body: JSON.stringify({
      ...body,
      max_depth: body.max_depth ?? 6,
      relation_types: body.relation_types ?? ['prerequisite_of'],
      limit: body.limit ?? 3,
    }),
  })
}
