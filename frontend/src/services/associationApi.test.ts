import { beforeEach, describe, expect, it, vi } from 'vitest'

import { findConceptAssociations } from './associationApi'

describe('associationApi', () => {
  beforeEach(() => {
    localStorage.clear()
    vi.restoreAllMocks()
  })

  it('posts the explicit association query and returns its Coach attribution', async () => {
    const responseBody = {
      associations: [{ concept_id: 7, concept_name: '贝叶斯定理' }],
      event: { id: 'ce_assoc' },
      nudge: { id: 'cn_assoc', skill_id: 'association_recall', status: 'pending' },
    }
    const fetchMock = vi.fn(async () => new Response(JSON.stringify(responseBody), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }))
    vi.stubGlobal('fetch', fetchMock)

    const result = await findConceptAssociations('开始学贝叶斯定理', 5)

    expect(result).toEqual(responseBody)
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/concepts/associate',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ text: '开始学贝叶斯定理', limit: 5 }),
      }),
    )
  })
})
