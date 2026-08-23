import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('antd', () => ({
  message: {
    error: vi.fn(),
    warning: vi.fn(),
  },
}))

import {
  addConceptAlias,
  applyConceptOverride,
  clearConceptOverride,
  deleteConcept,
  getConceptDetail,
  getConceptEvidence,
  getConceptState,
  getLearningRecommendations,
  mergeConcept,
  recomputeConceptState,
  renameConcept,
  reviewConcept,
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

  it('loads reviewable concept provenance and explainable recommendations', async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({ items: [], total: 0 }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }))
    vi.stubGlobal('fetch', fetchMock)

    await getConceptDetail(7)
    await getLearningRecommendations(6)

    expect(fetchMock).toHaveBeenNthCalledWith(1, '/api/concepts/7', expect.any(Object))
    expect(fetchMock).toHaveBeenNthCalledWith(2, '/api/learner-model/recommendations?limit=6', expect.any(Object))
  })

  it('edits, reviews, merges and deletes user-confirmed concept identities', async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({ id: 9 }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }))
    vi.stubGlobal('fetch', fetchMock)

    await addConceptAlias(9, 'Reciprocal Rank Fusion')
    await renameConcept(9, 'RRF')
    await reviewConcept(9, 'confirmed')
    await mergeConcept(9, 12)
    await deleteConcept(9)

    expect(fetchMock).toHaveBeenNthCalledWith(
      1, '/api/concepts/9/aliases',
      expect.objectContaining({ method: 'POST', body: JSON.stringify({ alias: 'Reciprocal Rank Fusion' }) }),
    )
    expect(fetchMock).toHaveBeenNthCalledWith(
      2, '/api/concepts/9',
      expect.objectContaining({ method: 'PATCH', body: JSON.stringify({ name: 'RRF' }) }),
    )
    expect(fetchMock).toHaveBeenNthCalledWith(
      3, '/api/concepts/9/review',
      expect.objectContaining({ method: 'POST', body: JSON.stringify({ review_status: 'confirmed' }) }),
    )
    expect(fetchMock).toHaveBeenNthCalledWith(
      4, '/api/concepts/9/merge',
      expect.objectContaining({ method: 'POST', body: JSON.stringify({ source_concept_id: 12 }) }),
    )
    expect(fetchMock).toHaveBeenNthCalledWith(5, '/api/concepts/9', expect.objectContaining({ method: 'DELETE' }))
  })
})
