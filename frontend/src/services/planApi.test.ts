import { beforeEach, describe, expect, it, vi } from 'vitest'
import { readPlanDraft, writePlanDraft, listPlans, savePlan } from './planApi'
import { setApiSessionUser } from './sessionScope'
const api = vi.hoisted(() => ({ apiFetch: vi.fn() }))
vi.mock('./apiClient', () => api)
beforeEach(() => { localStorage.clear(); vi.clearAllMocks(); setApiSessionUser(1) })
describe('plan drafts and versioned saves', () => {
  it('keeps drafts and their base version isolated by account and day', () => {
    writePlanDraft('2026-09-28', { content: '我的复盘', version: 3 })
    setApiSessionUser(2)
    expect(readPlanDraft('2026-09-28')).toBeNull()
    setApiSessionUser(1)
    expect(readPlanDraft('2026-09-28')).toEqual({ content: '我的复盘', version: 3 })
    expect(readPlanDraft('2026-09-29')).toBeNull()
  })
  it('submits the editor base version, not a newer background response', async () => {
    api.apiFetch.mockResolvedValueOnce([{ date: '2026-09-28', content: '新的内容', version: 8 }])
    await listPlans('2026-09-28', '2026-09-28')
    api.apiFetch.mockRejectedValueOnce(new Error('conflict'))
    await expect(savePlan('2026-09-28', '旧草稿', 3)).rejects.toThrow('conflict')
    expect(JSON.parse(api.apiFetch.mock.calls[1][1].body).expected_version).toBe(3)
  })
  it('rejects an old login response before it can update the version cache', async () => {
    let resolve!: (value: unknown) => void
    api.apiFetch.mockReturnValueOnce(new Promise(r => { resolve = r }))
    const pending = listPlans('2026-09-28', '2026-09-28')
    setApiSessionUser(2)
    resolve([{ date: '2026-09-28', content: 'other', version: 9 }])
    await expect(pending).rejects.toThrow('登录会话已变化')
  })
})
