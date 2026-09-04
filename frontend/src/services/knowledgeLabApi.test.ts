import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('antd', () => ({
  message: { error: vi.fn(), warning: vi.fn() },
}))

import {
  getMaterialClaims,
  reviewLabClaim,
  runLabAssociation,
  runLabKnowledgePath,
  uploadLabMaterial,
} from './knowledgeLabApi'

describe('knowledgeLabApi', () => {
  beforeEach(() => {
    localStorage.clear()
    vi.restoreAllMocks()
  })

  it('uploads a material through the existing canonical material endpoint', async () => {
    const fetchMock = vi.fn(async (_url: string, options?: RequestInit) => {
      expect(options?.body).toBeInstanceOf(FormData)
      const form = options?.body as FormData
      expect(form.get('title')).toBe('agent-notes.md')
      expect(form.get('sync_to_rag')).toBe('true')
      return new Response(JSON.stringify({ id: 11, title: 'agent-notes.md' }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      })
    })
    vi.stubGlobal('fetch', fetchMock)

    await uploadLabMaterial(new File(['# Agent'], 'agent-notes.md', { type: 'text/markdown' }))

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/materials/upload',
      expect.objectContaining({ method: 'POST' }),
    )
  })

  it('loads one material claim snapshot and submits domain claim review', async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({ claims: [] }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }))
    vi.stubGlobal('fetch', fetchMock)

    await getMaterialClaims(21, 'pending')
    await reviewLabClaim(42, 'confirmed')

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      '/api/knowledge/materials/21/claims?review_status=pending&limit=300',
      expect.any(Object),
    )
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      '/api/knowledge/claims/42/review',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ review_status: 'confirmed' }),
      }),
    )
  })

  it('sends material-scoped Association requests without inventing a lab backend', async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({ associations: [], diagnostics: {} }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }))
    vi.stubGlobal('fetch', fetchMock)

    await runLabAssociation({
      text: 'Tool Calling 和 Agent Runtime 有什么联系？',
      source_type: 'material',
      source_id: 9,
    })

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/knowledge/associate',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({
          text: 'Tool Calling 和 Agent Runtime 有什么联系？',
          source_type: 'material',
          source_id: 9,
          limit: 5,
        }),
      }),
    )
  })

  it('uses the Stage 7 Knowledge Path API with bounded defaults', async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({ status: 'no_path', paths: [] }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }))
    vi.stubGlobal('fetch', fetchMock)

    await runLabKnowledgePath({ start_concept_ids: [3, 5], target_concept_id: 8 })

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/knowledge/learning-path',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({
          start_concept_ids: [3, 5],
          target_concept_id: 8,
          max_depth: 6,
          relation_types: ['prerequisite_of'],
          limit: 3,
        }),
      }),
    )
  })
})
