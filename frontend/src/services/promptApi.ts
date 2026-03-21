import { apiFetch } from './apiClient'

export interface PromptTemplate {
  mode_key: string
  mode_name: string
  content: string
  is_custom: boolean
  updated_at: string | null
}

export interface PromptListResponse {
  templates: PromptTemplate[]
}

export async function listPrompts(): Promise<PromptListResponse | null> {
  try {
    const res = await apiFetch('/api/prompts')
    if (!res.ok) return null
    return res.json()
  } catch {
    return null
  }
}

export async function updatePrompt(modeKey: string, content: string): Promise<boolean> {
  try {
    const res = await apiFetch(`/api/prompts/${modeKey}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content }),
    })
    return res.ok
  } catch {
    return false
  }
}

export async function resetPrompt(modeKey: string): Promise<boolean> {
  try {
    const res = await apiFetch(`/api/prompts/${modeKey}`, {
      method: 'DELETE',
    })
    return res.ok
  } catch {
    return false
  }
}
