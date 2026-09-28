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

import { setApiSessionUser } from '../services/sessionScope'
import { switchPomodoroAccount, POMODORO_BACKGROUND_PREFERENCE_KEY, usePomodoroStore } from './pomodoroStore'

describe('pomodoro desktop reminder sync', () => {
  it('ignores rapid repeated starts without losing the active identity', () => {
    usePomodoroStore.getState().startTimer('Read', 25)
    const id = usePomodoroStore.getState().currentStartRequestKey
    usePomodoroStore.getState().startTimer('Read', 25)
    expect(usePomodoroStore.getState().currentStartRequestKey).toBe(id)
    expect(pomodoroApiMock.startPomodoro).toHaveBeenCalledTimes(1)
  })

  it('preserves interrupted focus time without counting it as a completed pomodoro', async () => {
    usePomodoroStore.getState().startTimer('Read', 25)
    await Promise.resolve()
    usePomodoroStore.getState().completeTimer(300, { startBreak: false, completed: false, stopReason: 'interrupted' })
    expect(usePomodoroStore.getState().getStats()).toMatchObject({ todayCount: 0, todayMinutes: 5 })
    expect(usePomodoroStore.getState().getCumulativeStats()).toMatchObject({ totalCount: 0, totalMinutes: 5 })
  })

  it('never counts an ongoing pause as focus after window focus or explicit stop', async () => {
    usePomodoroStore.getState().startTimer('Read', 25)
    await Promise.resolve()
    vi.advanceTimersByTime(5 * 60 * 1000)
    usePomodoroStore.getState().pauseTimer()
    vi.advanceTimersByTime(30 * 60 * 1000)
    usePomodoroStore.getState().tick()
    expect(usePomodoroStore.getState().remainingTime).toBe(20 * 60)
    expect(usePomodoroStore.getState().records).toHaveLength(0)
    expect(pomodoroApiMock.completePomodoro).not.toHaveBeenCalled()
    usePomodoroStore.getState().completeTimer(undefined, { startBreak: false, completed: false, stopReason: 'interrupted' })
    expect(usePomodoroStore.getState().records[0].duration).toBe(5)
  })

  it('keeps pause accounting when the backend refresh returns the same active timer', async () => {
    usePomodoroStore.getState().startTimer('Read', 25)
    await Promise.resolve()
    vi.advanceTimersByTime(5 * 60 * 1000)
    usePomodoroStore.getState().pauseTimer()
    pomodoroApiMock.getRecentPomodoros.mockResolvedValueOnce([{ id: 7, duration: 25, task_name: 'Read', started_at: '2026-05-23T10:00:00Z', ended_at: null, completed: false }])
    await usePomodoroStore.getState().refreshRecordsFromBackend()
    expect(usePomodoroStore.getState().isPaused).toBe(true)
    expect(usePomodoroStore.getState().remainingTime).toBe(1200)
  })

  it('does not pause the next break when focus expires at the pause click', () => {
    usePomodoroStore.getState().startTimer('Read', 25)
    vi.advanceTimersByTime(25 * 60 * 1000)
    usePomodoroStore.getState().pauseTimer()
    expect(usePomodoroStore.getState()).toMatchObject({ timerMode: 'break', isRunning: true, isPaused: false })
    expect(usePomodoroStore.getState().records).toHaveLength(1)
  })
  it('keeps account records isolated and ignores late start responses', async () => {
    let finish!: (value: { id: number }) => void
    pomodoroApiMock.startPomodoro.mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
    usePomodoroStore.getState().startTimer('A private timer', 25)
    usePomodoroStore.getState().addRecord('A offline record', 5)
    setApiSessionUser(8)
    await switchPomodoroAccount(8)
    finish({ id: 77 })
    await Promise.resolve()
    expect(usePomodoroStore.getState().records).toHaveLength(0)
    expect(usePomodoroStore.getState().currentBackendId).toBeNull()
    expect(usePomodoroStore.getState().currentTask).toBe('')
    setApiSessionUser(7)
    await switchPomodoroAccount(7)
    expect(usePomodoroStore.getState().records[0].taskName).toBe('A offline record')
    expect(usePomodoroStore.getState().currentTask).toBe('A private timer')
  })

  it('retries the same record identity and preserves an interrupted outcome', async () => {
    pomodoroApiMock.batchCreatePomodoros.mockRejectedValueOnce(new Error('response lost'))
    usePomodoroStore.getState().startTimer('Read', 25)
    vi.advanceTimersByTime(5 * 60 * 1000)
    usePomodoroStore.getState().completeTimer(undefined, { completed: false, stopReason: 'distracted', note: '电话打断' })
    await usePomodoroStore.getState().syncPendingRecords()
    const first = pomodoroApiMock.batchCreatePomodoros.mock.calls[0][0][0]
    expect(usePomodoroStore.getState().records[0].synced).toBe(false)
    await usePomodoroStore.getState().syncPendingRecords()
    const retry = pomodoroApiMock.batchCreatePomodoros.mock.calls[1][0][0]
    expect(retry.client_record_id).toBe(first.client_record_id)
    expect(retry).toMatchObject({ completed: false, stop_reason: 'distracted', duration: 5, note: '电话打断' })
  })

  it('does not attribute ownerless legacy storage to the current account', async () => {
    localStorage.setItem('pomodoro-storage', JSON.stringify({ state: { records: [{ id: 'legacy', taskName: 'private' }] } }))
    await switchPomodoroAccount(8)
    expect(usePomodoroStore.getState().records).toHaveLength(0)
    expect(localStorage.getItem('pomodoro-storage')).toContain('private')
  })

  beforeEach(async () => {
    window.localStorage.clear()
    setApiSessionUser(7)
    await switchPomodoroAccount(7)
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-05-23T10:00:00Z'))
    vi.clearAllMocks()
    pomodoroApiMock.batchCreatePomodoros.mockResolvedValue({ ids: [8] })
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
      currentCoachActionAttemptId: null,
      currentStartRequestKey: null,
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

    const stored = JSON.parse(window.localStorage.getItem('pomodoro-storage:user:7') || '{}')

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

    expect(usePomodoroStore.getState().records).toMatchObject([
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

  it('closes the same backend timer when a Coach-linked focus timer is stopped immediately', async () => {
    pomodoroApiMock.startPomodoro.mockResolvedValueOnce({ id: 71 })
    pomodoroApiMock.completePomodoro.mockResolvedValueOnce({ id: 71 })

    usePomodoroStore.getState().startTimer('Coach focus', 5, null, 'ca-71')
    usePomodoroStore.getState().completeTimer(60, {
      startBreak: false,
      completed: false,
      stopReason: 'interrupted',
    })
    await Promise.resolve()
    await Promise.resolve()

    expect(pomodoroApiMock.batchCreatePomodoros).toHaveBeenCalledWith(
      [expect.objectContaining({ completed: false, stop_reason: 'interrupted', duration: 1,
        coach_action_attempt_id: 'ca-71', client_record_id: expect.any(String) })],
      [expect.any(String)], expect.any(Object),
    )
  })

  it('persists a custom background image and can reset it', () => {
    const backgroundImage = 'data:image/png;base64,cG9tb2Rvcm8='

    usePomodoroStore.getState().setBackgroundImage(backgroundImage)

    const stored = JSON.parse(window.localStorage.getItem('pomodoro-storage:user:7') || '{}')
    expect(stored.state.backgroundImage).toBe(backgroundImage)

    usePomodoroStore.getState().setBackgroundImage(null)

    const resetStored = JSON.parse(window.localStorage.getItem('pomodoro-storage:user:7') || '{}')
    expect(resetStored.state.backgroundImage).toBeNull()
  })

  it('saves custom background changes to desktop preferences', () => {
    const backgroundImage = '/api/images/pomodoro-new/raw'

    usePomodoroStore.getState().setBackgroundImage(backgroundImage)

    expect(desktopPreferencesMock.setDesktopPreference).toHaveBeenCalledWith(
      `${POMODORO_BACKGROUND_PREFERENCE_KEY}:7`,
      { backgroundImage },
    )

    usePomodoroStore.getState().setBackgroundImage(null)

    expect(desktopPreferencesMock.setDesktopPreference).toHaveBeenLastCalledWith(
      `${POMODORO_BACKGROUND_PREFERENCE_KEY}:7`,
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
    const stored = JSON.parse(window.localStorage.getItem('pomodoro-storage:user:7') || '{}')
    expect(stored.state.backgroundImage).toBe(desktopBackground)
    expect(desktopPreferencesMock.setDesktopPreference).not.toHaveBeenCalled()
  })

  it('keeps an explicit default background from desktop preferences from reviving stale storage', async () => {
    usePomodoroStore.setState({ backgroundImage: '/api/images/pomodoro-old/raw' })
    desktopPreferencesMock.getDesktopPreference.mockResolvedValueOnce({ backgroundImage: null })

    await usePomodoroStore.getState().loadBackgroundImagePreference()

    expect(usePomodoroStore.getState().backgroundImage).toBeNull()
    const stored = JSON.parse(window.localStorage.getItem('pomodoro-storage:user:7') || '{}')
    expect(stored.state.backgroundImage).toBeNull()
    expect(desktopPreferencesMock.setDesktopPreference).not.toHaveBeenCalled()
  })
})
