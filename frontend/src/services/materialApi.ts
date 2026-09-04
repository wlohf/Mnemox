import { apiFetch } from './apiClient'
import type { RetrievalProjectionStatus } from './aiSettingsApi'

export interface KnowledgeExtractionStatus {
  status: 'not_started' | 'queued' | 'running' | 'succeeded' | 'partial' | 'failed' | 'cancelled'
  pending_claim_count: number
  pending_resolution_count: number
  deterministic_status: string
  llm_status: string
}

export interface MaterialItem {
  id: number
  title: string
  file_path?: string | null
  file_type?: string | null
  content?: string | null
  content_status?: string | null
  created_at: string
  updated_at: string
  project_ids?: number[] | null
  retrieval_projection?: RetrievalProjectionStatus | null
  knowledge_extraction?: KnowledgeExtractionStatus | null
}

export interface MaterialUploadResult extends MaterialItem {
  duplicate: boolean
}

export interface MaterialSearchResult {
  material_id: number
  title: string
  score: number
  text: string
}

export interface MaterialChapter {
  id: number
  title: string
  parent_id?: number | null
  order_index?: number | null
  mastery_level?: number | null
}

export async function listMaterials(limit = 100, skip = 0): Promise<MaterialItem[]> {
  const requested = Math.max(0, limit)
  if (requested === 0) return []

  const items: MaterialItem[] = []
  let offset = Math.max(0, skip)
  while (items.length < requested) {
    const pageSize = Math.min(100, requested - items.length)
    const page = await apiFetch<MaterialItem[]>(`/api/materials/?skip=${offset}&limit=${pageSize}`)
    items.push(...page)
    if (page.length < pageSize) break
    offset += page.length
  }
  return items
}

export async function searchMaterials(
  query: string,
  options: { projectId?: number; topK?: number } = {},
): Promise<MaterialSearchResult[]> {
  const params = new URLSearchParams({ query })
  if (options.projectId != null) params.set('project_id', String(options.projectId))
  if (options.topK != null) params.set('top_k', String(options.topK))
  return apiFetch<MaterialSearchResult[]>(`/api/materials/search?${params.toString()}`)
}

export async function uploadMaterial(file: File, options: { title?: string; syncToRag?: boolean } = {}): Promise<MaterialUploadResult> {
  const formData = new FormData()
  formData.append('file', file)
  formData.append('title', options.title || file.name)
  formData.append('sync_to_rag', options.syncToRag === false ? 'false' : 'true')
  return apiFetch<MaterialUploadResult>('/api/materials/upload', {
    method: 'POST',
    body: formData,
  })
}

export async function getMaterial(materialId: number): Promise<MaterialItem> {
  return apiFetch<MaterialItem>(`/api/materials/${materialId}`)
}

export async function deleteMaterial(materialId: number): Promise<void> {
  await apiFetch(`/api/materials/${materialId}`, { method: 'DELETE' })
}

export async function listMaterialChapters(materialId: number): Promise<MaterialChapter[]> {
  return apiFetch<MaterialChapter[]>(`/api/materials/${materialId}/chapters`)
}
