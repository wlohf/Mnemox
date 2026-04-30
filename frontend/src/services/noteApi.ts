import { apiFetch } from './apiClient'

export interface NoteLink {
  id?: number
  link_type: 'task' | 'session' | 'material' | 'chapter' | string
  link_id: number
}

export interface NoteItem {
  id: number
  title: string
  content: string
  note_type?: string | null
  material_id?: number | null
  chapter_id?: number | null
  tags?: string[]
  links: NoteLink[]
  created_at?: string | null
  updated_at?: string | null
}

export async function listNotes(params?: {
  q?: string
  note_type?: string
  link_type?: string
  link_id?: number
  tag?: string
}): Promise<NoteItem[]> {
  const query = new URLSearchParams()
  if (params?.q) query.set('q', params.q)
  if (params?.note_type) query.set('note_type', params.note_type)
  if (params?.link_type) query.set('link_type', params.link_type)
  if (params?.link_id !== undefined) query.set('link_id', String(params.link_id))
  if (params?.tag) query.set('tag', params.tag)
  const qs = query.toString()
  try {
    return await apiFetch<NoteItem[]>(`/api/notes${qs ? `?${qs}` : ''}`)
  } catch {
    return []
  }
}

export async function createNote(data: {
  title: string
  content: string
  note_type?: string
  material_id?: number
  chapter_id?: number
  tags?: string[]
  links?: NoteLink[]
}): Promise<NoteItem | null> {
  try {
    return await apiFetch<NoteItem>('/api/notes', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    })
  } catch {
    return null
  }
}

export async function updateNote(id: number, data: Record<string, any>): Promise<NoteItem | null> {
  try {
    return await apiFetch<NoteItem>(`/api/notes/${id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    })
  } catch {
    return null
  }
}

export async function deleteNote(id: number): Promise<boolean> {
  try {
    await apiFetch(`/api/notes/${id}`, { method: 'DELETE' })
    return true
  } catch {
    return false
  }
}

export async function suggestNoteMetadata(content: string, context?: string): Promise<{ title: string; tags: string[] } | null> {
  try {
    return await apiFetch<{ title: string; tags: string[] }>('/api/notes/suggest-metadata', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content, context }),
    })
  } catch {
    return null
  }
}
