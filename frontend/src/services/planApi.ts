import { apiFetch } from './apiClient'
import { captureApiSession } from './sessionScope'

export interface PlanItem { date: string; content: string; version?: number }
export interface PlanDraft { content: string; version: number }
const versions = new Map<string, number>()
const key = (date: string) => `mnemox.plan-draft.${captureApiSession().userId}.${date}`
export function readPlanDraft(date: string): PlanDraft | null {
  try { return JSON.parse(localStorage.getItem(key(date)) || 'null') } catch { return null }
}
export function writePlanDraft(date: string, draft: PlanDraft | null) {
  if (draft) localStorage.setItem(key(date), JSON.stringify(draft))
  else localStorage.removeItem(key(date))
}
export async function listPlans(start: string, end: string): Promise<PlanItem[]> {
  const session = captureApiSession()
  const params = new URLSearchParams({ start, end })
  const rows = await apiFetch<PlanItem[]>(`/api/plans/?${params.toString()}`)
  session.assertActive()
  for (const row of rows) versions.set(`${session.userId}:${row.date}`, row.version ?? 0)
  return rows
}
export async function savePlan(date: string, content: string, version?: number): Promise<PlanItem> {
  const session = captureApiSession()
  const saved = await apiFetch<PlanItem>(`/api/plans/${date}`, {
    method: 'PUT', body: JSON.stringify({ content, expected_version: version ?? versions.get(`${session.userId}:${date}`) ?? 0 }),
  })
  session.assertActive()
  versions.set(`${session.userId}:${date}`, saved.version ?? 0)
  return saved
}

export const getPlan = (date: string) => apiFetch<PlanItem>(`/api/plans/${date}`)
