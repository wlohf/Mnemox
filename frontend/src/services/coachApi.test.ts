import { describe, expect, it } from 'vitest'

import { detectCoachChatEvent } from './coachApi'

describe('coachApi emotional event classifier', () => {
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
})
