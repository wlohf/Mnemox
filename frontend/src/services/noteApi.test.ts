import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('antd', () => ({
  message: {
    error: vi.fn(),
    warning: vi.fn(),
  },
}))

import { askAgentAboutNote, draftNoteReviewPrompt, draftTaskFromNoteSelection } from './noteApi'

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

describe('noteApi action endpoints', () => {
  beforeEach(() => {
    localStorage.clear()
    vi.restoreAllMocks()
  })

  it('calls note action draft endpoints', async () => {
    const fetchMock = mockJson({ ok: true, preview: { question: 'what next?', agent_prompt_preview: 'safe preview' } })

    await draftNoteReviewPrompt(5)
    await draftTaskFromNoteSelection(5, { selected_text: 'selected' })
    const ask = await askAgentAboutNote(5, { question: 'what next?', selected_text: 'clip' })

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      '/api/notes/5/actions/review-prompt/draft',
      expect.objectContaining({ method: 'POST' }),
    )
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      '/api/notes/5/actions/task-from-selection/draft',
      expect.objectContaining({ method: 'POST', body: JSON.stringify({ selected_text: 'selected' }) }),
    )
    expect(fetchMock).toHaveBeenNthCalledWith(
      3,
      '/api/notes/5/actions/ask-agent',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ instruction: 'what next?', selected_text: 'clip' }),
      }),
    )
    expect(ask?.preview?.agent_prompt_preview).toBe('safe preview')
  })
})
