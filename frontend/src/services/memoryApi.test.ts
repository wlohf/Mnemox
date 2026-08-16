import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('antd', () => ({
  message: {
    error: vi.fn(),
    warning: vi.fn(),
  },
}))

import { listMemoryDeclarations, listMemories } from './memoryApi'

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

  it('loads auditable declarations for one memory', async () => {
    const fetchMock = vi.fn(async () =>
      new Response(JSON.stringify([
        {
          id: 8,
          memory_id: 1,
          subject: 'user:1',
          predicate: 'style',
          value: '先给结论',
          valid_from: '2026-08-16T10:00:00',
          valid_to: null,
          observed_at: '2026-08-16T10:00:00',
          confidence: 0.9,
          review_status: 'confirmed',
          source_event_id: null,
          source_type: 'manual',
          source_id: 'memory:1',
          evidence: { kind: 'manual_memory_declaration' },
          created_by: 'user',
          model_version: 'manual-memory-declaration-v1',
          supersedes_id: null,
          created_at: '2026-08-16T10:00:00',
        },
      ]), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    )
    vi.stubGlobal('fetch', fetchMock)

    const declarations = await listMemoryDeclarations(1)

    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/api/memory/memories/1/declarations'),
      expect.any(Object),
    )
    expect(declarations[0]).toMatchObject({
      subject: 'user:1',
      review_status: 'confirmed',
      created_by: 'user',
    })
  })
})
