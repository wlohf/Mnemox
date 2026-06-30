import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('antd', () => ({
  message: {
    error: vi.fn(),
    warning: vi.fn(),
  },
}))

import { listMemories } from './memoryApi'

describe('memoryApi metadata fields', () => {
  beforeEach(() => {
    localStorage.clear()
    vi.restoreAllMocks()
  })

  it('preserves extended memory metadata from the API', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        new Response(JSON.stringify([
          {
            id: 1,
            memory_key: 'style',
            memory_value: '偏好短步骤',
            category: 'style',
            confidence: 0.8,
            source_type: 'learning_event',
            source_id: '9',
            evidence: [{ event_id: 9 }],
            review_status: 'staged',
            memory_type: 'semantic',
            material_id: 3,
          },
        ]), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      ),
    )

    const memories = await listMemories()

    expect(memories[0]).toMatchObject({
      source_type: 'learning_event',
      source_id: '9',
      review_status: 'staged',
      memory_type: 'semantic',
      material_id: 3,
    })
  })
})
