import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../services/pomodoroApi', () => ({
  startPomodoro: vi.fn().mockResolvedValue({ id: 7 }),
  completePomodoro: vi.fn().mockResolvedValue({ id: 7 }),
  batchCreatePomodoros: vi.fn().mockResolvedValue({ ids: [8] }),
}))

const reminderMock = vi.hoisted(() => ({
  setPomodoroReminder: vi.fn().mockResolvedValue(true),
  clearPomodoroReminder: vi.fn().mockResolvedValue(true),
}))

vi.mock('../services/desktopReminder', () => reminderMock)

import { usePomodoroStore } from './pomodoroStore'

describe('pomodoro desktop reminder sync', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-05-23T10:00:00Z'))
    vi.clearAllMocks()
    usePomodoroStore.setState({
      isRunning: false,
      isPaused: false,
      remainingTime: 25 * 60,
      currentTask: '',
      currentTaskId: null,
      duration: 25,
      focusDuration: 25,
      breakDuration: 5,
      timerMode: 'focus',
      currentBackendId: null,
      startedAt: null,
      pausedAt: null,
      pausedTotalMs: 0,
      records: [],
      backendOnline: false,
      migrated: false,
    })
  })

  it('schedules a desktop reminder when starting a focus timer', () => {
    usePomodoroStore.getState().startTimer('Read', 25)

    expect(reminderMock.setPomodoroReminder).toHaveBeenCalledWith({
      taskName: 'Read',
      dueAt: Date.parse('2026-05-23T10:25:00Z'),
      mode: 'focus',
    })
  })

  it('clears desktop reminders when pausing and resetting', () => {
    usePomodoroStore.getState().startTimer('Read', 25)
    usePomodoroStore.getState().pauseTimer()
    usePomodoroStore.getState().resetTimer()

    expect(reminderMock.clearPomodoroReminder).toHaveBeenCalledTimes(2)
  })
})
