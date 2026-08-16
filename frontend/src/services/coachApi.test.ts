import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  detectCoachChatEvent,
  markPendingCoachNudgesShown,
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
})
