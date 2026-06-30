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

const desktopPreferencesMock = vi.hoisted(() => ({
  getDesktopPreference: vi.fn().mockResolvedValue(null),
  setDesktopPreference: vi.fn().mockResolvedValue(true),
}))

vi.mock('../services/desktopPreferences', () => desktopPreferencesMock)

import { POMODORO_BACKGROUND_PREFERENCE_KEY, usePomodoroStore } from './pomodoroStore'

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
      backgroundImage: null,
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

  it('clears the current task when a focus timer is stopped without starting a break', () => {
    usePomodoroStore.getState().startTimer('Deep Work', 25)

    usePomodoroStore.getState().completeTimer(undefined, { startBreak: false })

    expect(usePomodoroStore.getState()).toMatchObject({
      isRunning: false,
      isPaused: false,
      currentTask: '',
      currentTaskId: null,
      timerMode: 'focus',
    })
  })

  it('persists a custom background image and can reset it', () => {
    const backgroundImage = 'data:image/png;base64,cG9tb2Rvcm8='

    usePomodoroStore.getState().setBackgroundImage(backgroundImage)

    const stored = JSON.parse(window.localStorage.getItem('pomodoro-storage') || '{}')
    expect(stored.state.backgroundImage).toBe(backgroundImage)

    usePomodoroStore.getState().setBackgroundImage(null)

    const resetStored = JSON.parse(window.localStorage.getItem('pomodoro-storage') || '{}')
    expect(resetStored.state.backgroundImage).toBeNull()
  })

  it('saves custom background changes to desktop preferences', () => {
    const backgroundImage = '/api/images/pomodoro-new/raw'

    usePomodoroStore.getState().setBackgroundImage(backgroundImage)

    expect(desktopPreferencesMock.setDesktopPreference).toHaveBeenCalledWith(
      POMODORO_BACKGROUND_PREFERENCE_KEY,
      { backgroundImage },
    )

    usePomodoroStore.getState().setBackgroundImage(null)

    expect(desktopPreferencesMock.setDesktopPreference).toHaveBeenLastCalledWith(
      POMODORO_BACKGROUND_PREFERENCE_KEY,
      { backgroundImage: null },
    )
  })

  it('loads custom background from desktop preferences over stale current-origin storage', async () => {
    const staleBackground = '/api/images/pomodoro-old/raw'
    const desktopBackground = '/api/images/pomodoro-new/raw'
    usePomodoroStore.setState({ backgroundImage: staleBackground })
    desktopPreferencesMock.getDesktopPreference.mockResolvedValueOnce({ backgroundImage: desktopBackground })

    await usePomodoroStore.getState().loadBackgroundImagePreference()

    expect(usePomodoroStore.getState().backgroundImage).toBe(desktopBackground)
    const stored = JSON.parse(window.localStorage.getItem('pomodoro-storage') || '{}')
    expect(stored.state.backgroundImage).toBe(desktopBackground)
    expect(desktopPreferencesMock.setDesktopPreference).not.toHaveBeenCalled()
  })

  it('keeps an explicit default background from desktop preferences from reviving stale storage', async () => {
    usePomodoroStore.setState({ backgroundImage: '/api/images/pomodoro-old/raw' })
    desktopPreferencesMock.getDesktopPreference.mockResolvedValueOnce({ backgroundImage: null })

    await usePomodoroStore.getState().loadBackgroundImagePreference()

    expect(usePomodoroStore.getState().backgroundImage).toBeNull()
    const stored = JSON.parse(window.localStorage.getItem('pomodoro-storage') || '{}')
    expect(stored.state.backgroundImage).toBeNull()
    expect(desktopPreferencesMock.setDesktopPreference).not.toHaveBeenCalled()
  })
})
