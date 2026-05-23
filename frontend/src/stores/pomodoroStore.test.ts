import { beforeEach, describe, expect, it, vi } from 'vitest'

const pomodoroApiMock = vi.hoisted(() => ({
  startPomodoro: vi.fn().mockResolvedValue({ id: 7 }),
  completePomodoro: vi.fn().mockResolvedValue({ id: 7 }),
  batchCreatePomodoros: vi.fn().mockResolvedValue({ ids: [8] }),
  getRecentPomodoros: vi.fn().mockResolvedValue([]),
}))

vi.mock('../services/pomodoroApi', () => ({
  ...pomodoroApiMock,
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
    window.localStorage.clear()
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

  it('persists an active focus timer so it can survive a desktop restart', () => {
    usePomodoroStore.getState().startTimer('Read', 25)

    const stored = JSON.parse(window.localStorage.getItem('pomodoro-storage') || '{}')

    expect(stored.state).toMatchObject({
      isRunning: true,
      isPaused: false,
      remainingTime: 25 * 60,
      currentTask: 'Read',
      duration: 25,
      timerMode: 'focus',
      startedAt: Date.parse('2026-05-23T10:00:00Z'),
    })
  })

  it('loads completed records from the backend when local storage is empty after restart', async () => {
    pomodoroApiMock.getRecentPomodoros.mockResolvedValueOnce([
      {
        id: 42,
        chapter_id: null,
        task_id: null,
        task_name: 'Algorithms',
        started_at: '2026-05-23T08:30:00Z',
        ended_at: '2026-05-23T09:00:00Z',
        duration: 30,
        completed: true,
        note: null,
        created_at: '2026-05-23T08:30:00Z',
      },
    ])

    await usePomodoroStore.getState().refreshRecordsFromBackend()

    expect(usePomodoroStore.getState().records).toEqual([
      {
        id: 'backend-42',
        backendId: 42,
        taskId: null,
        taskName: 'Algorithms',
        duration: 30,
        completedAt: '2026-05-23T09:00:00Z',
        date: '2026-05-23',
        synced: true,
      },
    ])
  })

  it('recovers an active backend timer when reopening before it expires', async () => {
    pomodoroApiMock.getRecentPomodoros.mockResolvedValueOnce([
      {
        id: 43,
        chapter_id: null,
        task_id: 9,
        task_name: 'Databases',
        started_at: '2026-05-23T09:55:00Z',
        ended_at: null,
        duration: 25,
        completed: false,
        note: null,
        created_at: '2026-05-23T09:55:00Z',
      },
    ])

    await usePomodoroStore.getState().refreshRecordsFromBackend()

    expect(usePomodoroStore.getState()).toMatchObject({
      isRunning: true,
      isPaused: false,
      remainingTime: 20 * 60,
      currentTask: 'Databases',
      currentTaskId: 9,
      duration: 25,
      focusDuration: 25,
      timerMode: 'focus',
      currentBackendId: 43,
      startedAt: Date.parse('2026-05-23T09:55:00Z'),
      pausedAt: null,
      pausedTotalMs: 0,
    })
  })
})
