import { apiFetch } from './apiClient'

export interface PlanItem {
  date: string
  content: string
}

export async function listPlans(start: string, end: string): Promise<PlanItem[]> {
  const params = new URLSearchParams({ start, end })
  return apiFetch<PlanItem[]>(`/api/plans/?${params.toString()}`)
}

export async function savePlan(date: string, content: string): Promise<PlanItem> {
  return apiFetch<PlanItem>(`/api/plans/${date}`, {
    method: 'PUT',
    body: JSON.stringify({ content }),
  })
}
