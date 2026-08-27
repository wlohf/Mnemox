import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  confirmCoachNudgeDraft,
  detectCoachChatEvent,
  markPendingCoachNudgesShown,
  startCoachNudgeAction,
  type CoachNudge,
} from './coachApi'

describe('coachApi emotional event classifier', () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('detects low motivation text', () => {
    expect(detectCoachChatEvent('我学不进去了')).toBe('chat.low_motivation_detected')
    expect(detectCoachChatEvent("I can't study today")).toBe('chat.low_motivation_detected')
  })

  it('detects frustration before generic low motivation', () => {
    expect(detectCoachChatEvent('我感觉自己很差，什么都做不到')).toBe('chat.frustration_detected')
    expect(detectCoachChatEvent('I feel hopeless')).toBe('chat.frustration_detected')
  })

  it('detects overload as a minimum-next-step event', () => {
    expect(detectCoachChatEvent('任务太多了，我不知道先做什么')).toBe('chat.overload_detected')
    expect(detectCoachChatEvent('too much homework, where to start?')).toBe('chat.overload_detected')
  })

  it('returns null for neutral text', () => {
    expect(detectCoachChatEvent('请解释一下这段材料')).toBeNull()
  })

  it('marks each visible pending nudge once and leaves existing lifecycle states alone', async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({
      id: 'nudge-1',
      status: 'shown',
    }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }))
    vi.stubGlobal('fetch', fetchMock)
    const nudges = [
      { id: 'nudge-1', status: 'pending' },
      { id: 'nudge-1', status: 'pending' },
      { id: 'nudge-2', status: 'accepted' },
    ] as CoachNudge[]

    const marked = await markPendingCoachNudgesShown(nudges)

    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/coach/nudges/nudge-1/shown',
      expect.objectContaining({ method: 'POST' }),
    )
    expect(marked).toEqual([{ id: 'nudge-1', status: 'shown' }])
  })

  it('starts a Coach action before handing it to a real learning surface', async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({
      ok: true,
      idempotent: false,
      nudge: { id: 'nudge-1', status: 'started', route: '/pomodoro', requires_confirmation: false },
      attempt: { id: 'ca-1', nudge_id: 'nudge-1', action_type: 'start_focus', action_payload: {}, status: 'started' },
    }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }))
    vi.stubGlobal('fetch', fetchMock)

    const started = await startCoachNudgeAction('nudge-1')

    expect(started?.attempt.id).toBe('ca-1')
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/coach/nudges/nudge-1/start',
      expect.objectContaining({ method: 'POST' }),
    )
  })

  it('confirms a Coach plan draft explicitly instead of writing on navigation', async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({ ok: true, result: { route: '/plans' } }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }))
    vi.stubGlobal('fetch', fetchMock)

    await confirmCoachNudgeDraft('nudge-1', 'ca-1')

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/coach/nudges/nudge-1/draft/confirm',
      expect.objectContaining({ method: 'POST', body: JSON.stringify({ attempt_id: 'ca-1' }) }),
    )
  })
})
