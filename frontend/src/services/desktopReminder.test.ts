import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
  clearPomodoroReminder,
  isDesktopReminderAvailable,
  onReminderTriggered,
  setPomodoroReminder,
} from './desktopReminder'

describe('desktopReminder bridge wrapper', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    delete window.mnemoxDesktop
  })

  it('safely no-ops outside Electron', async () => {
    expect(isDesktopReminderAvailable()).toBe(false)
    await expect(setPomodoroReminder({ taskName: 'Focus', dueAt: 123, mode: 'focus' })).resolves.toBe(false)
    await expect(clearPomodoroReminder()).resolves.toBe(false)
    expect(onReminderTriggered(() => {})).toBeNull()
  })

  it('delegates reminder operations to the desktop bridge', async () => {
    const unsubscribe = vi.fn()
    const callback = vi.fn()
    window.mnemoxDesktop = {
      setPomodoroReminder: vi.fn().mockResolvedValue(undefined),
      clearPomodoroReminder: vi.fn().mockResolvedValue(undefined),
      onReminderTriggered: vi.fn().mockReturnValue(unsubscribe),
    } as any

    await expect(setPomodoroReminder({ taskName: 'Focus', dueAt: 123, mode: 'focus' })).resolves.toBe(true)
    await expect(clearPomodoroReminder()).resolves.toBe(true)
    expect(onReminderTriggered(callback)).toBe(unsubscribe)

    expect(window.mnemoxDesktop!.setPomodoroReminder).toHaveBeenCalledWith({
      taskName: 'Focus',
      dueAt: 123,
      mode: 'focus',
    })
  })
})
