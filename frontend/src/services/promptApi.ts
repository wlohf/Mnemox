import { apiFetch } from './apiClient'

export interface PromptTemplate {
  mode_key: string
  name: string
  content: string
  is_custom: boolean
  updated_at?: string | null
}

export interface PromptListResponse {
  templates: PromptTemplate[]
}

export async function listPrompts(): Promise<PromptListResponse | null> {
  try {
    const arr = await apiFetch<PromptTemplate[]>('/api/prompts')
    return { templates: arr }
  } catch {
    return null
  }
}

export async function updatePrompt(modeKey: string, content: string): Promise<boolean> {
  try {
    await apiFetch(`/api/prompts/${modeKey}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content }),
    })
    return true
  } catch {
    return false
  }
}

export async function resetPrompt(modeKey: string): Promise<boolean> {
  try {
    await apiFetch(`/api/prompts/${modeKey}`, { method: 'DELETE' })
    return true
  } catch {
    return false
  }
}
