import { apiFetch } from './apiClient'

export interface AgentInfo {
  name: string
  description: string
}

export interface AgentRunResponse<T = any> {
  agent: string
  result: T
}

export async function listAgents(): Promise<AgentInfo[]> {
  try {
    return await apiFetch<AgentInfo[]>('/api/agent')
  } catch {
    return []
  }
}

export async function runAgent<T = any>(agentName: string, payload: Record<string, any> = {}): Promise<AgentRunResponse<T> | null> {
  try {
    return await apiFetch<AgentRunResponse<T>>(`/api/agent/${agentName}/run`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ payload }),
    })
  } catch {
    return null
  }
}
