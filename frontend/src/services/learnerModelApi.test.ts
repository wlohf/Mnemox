import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('antd', () => ({
  message: {
    error: vi.fn(),
    warning: vi.fn(),
  },
}))

import {
  applyConceptOverride,
  clearConceptOverride,
  getConceptEvidence,
  getConceptState,
  recomputeConceptState,
} from './learnerModelApi'

describe('learnerModelApi', () => {
  beforeEach(() => {
    localStorage.clear()
    vi.restoreAllMocks()
  })

  it('uses the user-scoped state and paginated evidence endpoints', async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({ items: [], total: 0 }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }))
    vi.stubGlobal('fetch', fetchMock)

    await getConceptState(7)
    await getConceptEvidence(7, { offset: 40, limit: 20, evidenceCategory: 'direct' })

    expect(fetchMock).toHaveBeenNthCalledWith(1, '/api/learner-model/concepts/7/state', expect.any(Object))
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      '/api/learner-model/concepts/7/evidence?offset=40&limit=20&evidence_category=direct',
      expect.any(Object),
    )
  })

  it('applies, clears and recomputes a concept correction', async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({ state: {} }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }))
    vi.stubGlobal('fetch', fetchMock)

    await applyConceptOverride(9, { mastery_estimate: 88, reason: '口试复核' })
    await clearConceptOverride(9, '撤销复核')
    await recomputeConceptState(9)

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      '/api/learner-model/concepts/9/override',
      expect.objectContaining({ method: 'POST', body: JSON.stringify({ mastery_estimate: 88, reason: '口试复核' }) }),
    )
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      '/api/learner-model/concepts/9/override?reason=%E6%92%A4%E9%94%80%E5%A4%8D%E6%A0%B8',
      expect.objectContaining({ method: 'DELETE' }),
    )
    expect(fetchMock).toHaveBeenNthCalledWith(
      3,
      '/api/learner-model/concepts/9/recompute',
      expect.objectContaining({ method: 'POST' }),
    )
  })
})
