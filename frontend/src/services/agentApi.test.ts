import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('antd', () => ({
  message: {
    error: vi.fn(),
    warning: vi.fn(),
  },
}))

import {
  confirmAgentMemoryCandidate,
  getAgentCoreProfile,
  ignoreAgentMemoryCandidate,
  runAgentMemoryLearning,
} from './agentApi'

function mockJson(body: unknown) {
  const fetchMock = vi.fn(async (_url: string, _options?: RequestInit) =>
    new Response(JSON.stringify(body), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }),
  )
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

describe('agentApi memory endpoints', () => {
  beforeEach(() => {
    localStorage.clear()
    vi.restoreAllMocks()
  })

  it('normalizes wrapped core profile responses', async () => {
    mockJson({
      memory: { id: 7, memory_key: 'agent_core_profile', updated_at: '2026-06-24T00:00:00' },
      profile: { summary: [{ category: 'goal', items: ['英语听力'] }], updated_at: '2026-06-24T00:00:00' },
    })

    const profile = await getAgentCoreProfile()

    expect(profile?.id).toBe(7)
    expect(profile?.memory_key).toBe('agent_core_profile')
    expect(profile?.memory_value).toContain('英语听力')
  })

  it('posts candidate review actions with the expected body', async () => {
    const fetchMock = mockJson({ ok: true })

    await confirmAgentMemoryCandidate(42, { lock: true })
    await ignoreAgentMemoryCandidate(42, { reason: 'inaccurate' })
    await runAgentMemoryLearning()

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      '/api/agent/memory/candidates/42/confirm',
      expect.objectContaining({ method: 'POST', body: JSON.stringify({ lock: true }) }),
    )
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      '/api/agent/memory/candidates/42/ignore',
      expect.objectContaining({ method: 'POST', body: JSON.stringify({ reason: 'inaccurate' }) }),
    )
    expect(fetchMock).toHaveBeenNthCalledWith(
      3,
      '/api/agent/memory/run-learning',
      expect.objectContaining({ method: 'POST' }),
    )
  })
})
