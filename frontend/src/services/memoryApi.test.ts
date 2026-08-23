import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('antd', () => ({
  message: {
    error: vi.fn(),
    warning: vi.fn(),
  },
}))

import {
  correctMemory,
  expireMemories,
  listMemoryConflicts,
  listMemoryDeclarations,
  listMemories,
  reviewMemoryCandidate,
} from './memoryApi'

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
          fact_key: 'preferred_style',
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
          conflicts_with_id: null,
          resolution_reason: null,
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

  it('loads staged conflicts with the currently effective fact', async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify([{
      fact_key: 'learning_goal',
      current_memory_id: 2,
      candidate_memory_id: 5,
      current: { id: 3, value: '先学习检索' },
      candidate: { id: 8, value: '先学习工具调用', conflicts_with_id: 3 },
    }]), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }))
    vi.stubGlobal('fetch', fetchMock)

    const conflicts = await listMemoryConflicts()

    expect(fetchMock).toHaveBeenCalledWith('/api/memory/conflicts', expect.any(Object))
    expect(conflicts[0]).toMatchObject({ fact_key: 'learning_goal', candidate_memory_id: 5 })
  })

  it('submits auditable corrections with validity and reason', async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({ id: 7, review_status: 'confirmed' }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }))
    vi.stubGlobal('fetch', fetchMock)

    await correctMemory(7, {
      memory_value: '先做真实项目',
      reason: '旧偏好不准确',
      expires_at: '2026-09-01T18:00:00',
    })

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/memory/memories/7/correct',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({
          memory_value: '先做真实项目',
          reason: '旧偏好不准确',
          expires_at: '2026-09-01T18:00:00',
        }),
      }),
    )
  })

  it('confirms or rejects conflict candidates through the existing review gate', async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({ id: 9 }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }))
    vi.stubGlobal('fetch', fetchMock)

    await reviewMemoryCandidate(9, 'confirm', true)
    await reviewMemoryCandidate(9, 'inaccurate')

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      '/api/agent/memory/candidates/9/confirm',
      expect.objectContaining({ method: 'POST', body: JSON.stringify({ lock: true }) }),
    )
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      '/api/agent/memory/candidates/9/ignore',
      expect.objectContaining({ method: 'POST', body: JSON.stringify({ reason: 'inaccurate' }) }),
    )
  })

  it('runs user-scoped expiration maintenance', async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({ expired_count: 1, memory_ids: [4] }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }))
    vi.stubGlobal('fetch', fetchMock)

    const result = await expireMemories()

    expect(fetchMock).toHaveBeenCalledWith('/api/memory/expire', expect.objectContaining({ method: 'POST' }))
    expect(result).toEqual({ expired_count: 1, memory_ids: [4] })
  })
})
