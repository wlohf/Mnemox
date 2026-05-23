import { apiFetch } from './apiClient'

const CONV_BASE = '/api/conversations'
const PROJ_BASE = '/api/chat-projects'

// ---- Conversation types ----

export interface Conversation {
  id: number
  title: string
  project_id: number | null
  is_pinned: boolean
  summary: string | null
  matched_preview?: string | null
  created_at: string
  updated_at: string
}

export interface ConversationMessage {
  id: number
  role: 'user' | 'assistant'
  content: string
  image_data: string[] | null
  created_at: string
}

export interface ConversationDetail extends Conversation {
  messages: ConversationMessage[]
}

export interface ConversationMessageCreate {
  role: 'user' | 'assistant'
  content: string
  image_data?: string[] | null
}

// ---- Project types ----

export interface ChatProject {
  id: number
  name: string
  description: string | null
  default_instructions: string | null
  color: string
  is_archived: boolean
  conversation_count: number
  material_ids?: number[]
  created_at: string
  updated_at: string
}

// ---- Conversation API ----

export async function listConversations(params?: {
  project_id?: number
  search?: string
}): Promise<Conversation[]> {
  const query = new URLSearchParams()
  if (params?.project_id !== undefined) query.set('project_id', String(params.project_id))
  if (params?.search) query.set('search', params.search)
  const qs = query.toString()
  return await apiFetch<Conversation[]>(`${CONV_BASE}${qs ? '?' + qs : ''}`)
}

export async function createConversation(data: {
  title?: string
  project_id?: number | null
}): Promise<Conversation> {
  return await apiFetch<Conversation>(CONV_BASE, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
}

export async function getConversation(id: number): Promise<ConversationDetail> {
  return await apiFetch<ConversationDetail>(`${CONV_BASE}/${id}`)
}

export async function appendConversationMessages(
  id: number,
  messages: ConversationMessageCreate[],
): Promise<ConversationMessage[]> {
  const res = await apiFetch<{ messages: ConversationMessage[] }>(`${CONV_BASE}/${id}/messages`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(messages),
  })
  return res.messages
}

export async function updateConversation(
  id: number,
  data: { title?: string; is_pinned?: boolean; project_id?: number | null }
): Promise<Conversation> {
  return await apiFetch<Conversation>(`${CONV_BASE}/${id}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
}

export async function forkConversation(
  id: number,
  data: { title?: string; up_to_index?: number | null }
): Promise<Conversation> {
  return await apiFetch<Conversation>(`${CONV_BASE}/${id}/fork`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
}

export async function deleteConversation(id: number): Promise<boolean> {
  await apiFetch(`${CONV_BASE}/${id}`, { method: 'DELETE' })
  return true
}

// ---- Project API ----

export async function listProjects(): Promise<ChatProject[]> {
  return await apiFetch<ChatProject[]>(PROJ_BASE)
}

export async function createProject(data: {
  name: string
  description?: string
  default_instructions?: string
  color?: string
}): Promise<ChatProject> {
  return await apiFetch<ChatProject>(PROJ_BASE, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
}

export async function getProject(id: number): Promise<ChatProject> {
  return await apiFetch<ChatProject>(`${PROJ_BASE}/${id}`)
}

export async function updateProject(
  id: number,
  data: { name?: string; description?: string; default_instructions?: string; color?: string; is_archived?: boolean }
): Promise<ChatProject> {
  return await apiFetch<ChatProject>(`${PROJ_BASE}/${id}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
}

export async function deleteProject(id: number): Promise<boolean> {
  await apiFetch(`${PROJ_BASE}/${id}`, { method: 'DELETE' })
  return true
}

export async function addProjectMaterial(projectId: number, materialId: number): Promise<boolean> {
  await apiFetch(`${PROJ_BASE}/${projectId}/materials`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ material_id: materialId }),
  })
  return true
}

export async function removeProjectMaterial(projectId: number, materialId: number): Promise<boolean> {
  await apiFetch(`${PROJ_BASE}/${projectId}/materials/${materialId}`, { method: 'DELETE' })
  return true
}

export async function batchUpdateProjectMaterials(
  projectId: number,
  addIds: number[],
  removeIds: number[]
): Promise<boolean> {
  await apiFetch(`${PROJ_BASE}/${projectId}/materials`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      add_material_ids: addIds,
      remove_material_ids: removeIds,
    }),
  })
  return true
}

export interface MaterialArchiveResult {
  project_id: number
  project_name: string
  added_count: number
  total_unassigned: number
}

export async function archiveUnassignedMaterials(): Promise<MaterialArchiveResult> {
  return await apiFetch<MaterialArchiveResult>(`${PROJ_BASE}/materials/archive-unassigned`, { method: 'POST' })
}
