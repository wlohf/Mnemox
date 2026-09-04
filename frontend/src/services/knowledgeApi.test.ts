import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('antd', () => ({
  message: { error: vi.fn(), warning: vi.fn() },
}))

import {
  listResolutionCandidates,
  rebuildKnowledgeProjection,
  resolveKnowledgeCandidate,
} from './knowledgeApi'

describe('knowledgeApi', () => {
  beforeEach(() => {
    localStorage.clear()
    vi.restoreAllMocks()
  })

  it('loads the pending resolution queue for one material', async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({ candidates: [] }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }))
    vi.stubGlobal('fetch', fetchMock)

    await listResolutionCandidates({ sourceType: 'material', sourceId: 17, limit: 50 })

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/knowledge/resolution-candidates?decision=pending&limit=50&source_type=material&source_id=17',
      expect.any(Object),
    )
  })

  it('submits conservative review actions and explicit rebuilds', async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({ id: 8 }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }))
    vi.stubGlobal('fetch', fetchMock)

    await resolveKnowledgeCandidate(8, { action: 'link_add_alias', concept_id: 3 })
    await rebuildKnowledgeProjection(true)

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      '/api/knowledge/resolution-candidates/8/resolve',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ action: 'link_add_alias', concept_id: 3 }),
      }),
    )
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      '/api/knowledge/projection/rebuild?force=true',
      expect.objectContaining({ method: 'POST' }),
    )
  })
})

