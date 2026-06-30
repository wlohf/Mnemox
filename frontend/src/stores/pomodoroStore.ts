import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import * as pomodoroApi from '../services/pomodoroApi'
import type { PomodoroStartResponse } from '../services/pomodoroApi'
import { clearPomodoroReminder, setPomodoroReminder } from '../services/desktopReminder'
import { getDesktopPreference, setDesktopPreference } from '../services/desktopPreferences'

export interface PomodoroRecord {
  id: string
  backendId?: number
  taskId?: number | null
  taskName: string
  duration: number // in minutes
  completedAt: string // ISO date string
  date: string // YYYY-MM-DD format for easy grouping
  synced?: boolean
}

interface PomodoroStats {
  todayCount: number
  todayMinutes: number
  weekCount: number
  weekMinutes: number
  weeklyData: { date: string; count: number; minutes: number }[]
}

// 任务时长分布（用于饼图）
export interface TaskDistributionItem {
  taskName: string
  minutes: number
  count: number
  percentage: number
  color: string
}

// 累计统计
export interface CumulativeStats {
  totalCount: number
  totalMinutes: number
  totalHours: number
  dailyAverageMinutes: number
  firstRecordDate: string | null
  activeDays: number
}

// 时间范围类型
export type DateRange = 'day' | 'week' | 'month' | 'all'
export type PomodoroMode = 'focus' | 'break'

interface PomodoroState {
  // Current timer state
  isRunning: boolean
  isPaused: boolean
  remainingTime: number // in seconds
  currentTask: string
  currentTaskId: number | null
  duration: number // in minutes
  focusDuration: number // in minutes
  breakDuration: number // in minutes
  timerMode: PomodoroMode
  currentBackendId: number | null
  startedAt: number | null
  pausedAt: number | null
  pausedTotalMs: number
  backgroundImage: string | null

  // Records
  records: PomodoroRecord[]

  // Sync state
  backendOnline: boolean
  migrated: boolean

  // Actions
  startTimer: (taskName: string, duration: number, taskId?: number | null) => void
  startBreakTimer: (durationOverride?: number) => void
  setBreakDuration: (duration: number) => void
  pauseTimer: () => void
  resumeTimer: () => void
  completeTimer: (actualSeconds?: number, options?: { startBreak?: boolean }) => void
  resetTimer: (durationOverride?: number) => void
  tick: () => void
  addRecord: (taskName: string, duration: number) => void
  setBackgroundImage: (backgroundImage: string | null) => void
  loadBackgroundImagePreference: () => Promise<void>

  // Sync actions
  syncPendingRecords: () => Promise<void>
  migrateLocalRecords: () => Promise<void>
  refreshRecordsFromBackend: () => Promise<void>

  // Stats
  getStats: () => PomodoroStats
  getTodayRecords: () => PomodoroRecord[]
  getWeekRecords: () => PomodoroRecord[]

  // Enhanced Stats
  getTaskDistribution: (range: DateRange) => TaskDistributionItem[]
  getCumulativeStats: () => CumulativeStats
  getRecordsByRange: (range: DateRange) => PomodoroRecord[]
}

const getDateString = (date: Date = new Date()) => {
  return date.toISOString().split('T')[0]
}

const MAX_RECORDS = 500
const BACKEND_REFRESH_LIMIT = 500
const ACTIVE_TIMER_STALE_GRACE_MS = 12 * 60 * 60 * 1000
export const POMODORO_BACKGROUND_PREFERENCE_KEY = 'pomodoro.background'

interface PomodoroBackgroundPreference {
  backgroundImage: string | null
}

const getDateFromIso = (value: string) => {
  const datePrefix = value.match(/^\d{4}-\d{2}-\d{2}/)?.[0]
  if (datePrefix) return datePrefix

  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? getDateString() : getDateString(parsed)
}

const parseTimestamp = (value: string | null | undefined) => {
  if (!value) return Number.NaN
  return new Date(value).getTime()
}

const sortRecordsByCompletedAt = (records: PomodoroRecord[]) => {
  return [...records].sort((a, b) => parseTimestamp(b.completedAt) - parseTimestamp(a.completedAt))
}

const normalizePomodoroBackgroundPreference = (value: unknown): PomodoroBackgroundPreference | null => {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null
  if (!Object.prototype.hasOwnProperty.call(value, 'backgroundImage')) return null

  const backgroundImage = (value as Partial<PomodoroBackgroundPreference>).backgroundImage
  if (backgroundImage === null || typeof backgroundImage === 'string') {
    return { backgroundImage }
  }

  return null
}

const getRecordDedupKey = (record: PomodoroRecord) => {
  return [
    record.taskId ?? '',
    record.taskName.trim().toLowerCase(),
    record.duration,
    record.completedAt,
  ].join('|')
}

const mergeRecords = (backendRecords: PomodoroRecord[], localRecords: PomodoroRecord[]) => {
  const seenBackendIds = new Set<number>()
  const seenKeys = new Set<string>()
  const merged: PomodoroRecord[] = []

  for (const record of [...backendRecords, ...localRecords]) {
    if (record.backendId !== undefined) {
      if (seenBackendIds.has(record.backendId)) continue
      seenBackendIds.add(record.backendId)
    } else {
      const key = getRecordDedupKey(record)
      if (seenKeys.has(key)) continue
      seenKeys.add(key)
    }
    merged.push(record)
  }

  return sortRecordsByCompletedAt(merged).slice(0, MAX_RECORDS)
}

const toRecord = (pomodoro: PomodoroStartResponse, completedAtOverride?: string): PomodoroRecord | null => {
  const completedAt = completedAtOverride ?? pomodoro.ended_at
  if (!completedAt) return null

  return {
    id: `backend-${pomodoro.id}`,
    backendId: pomodoro.id,
    taskId: pomodoro.task_id,
    taskName: pomodoro.task_name?.trim() || '专注学习',
    duration: pomodoro.duration,
    completedAt,
    date: getDateFromIso(completedAt),
    synced: true,
  }
}

const getWeekStart = () => {
  const now = new Date()
  const dayOfWeek = now.getDay()
  const diff = now.getDate() - dayOfWeek + (dayOfWeek === 0 ? -6 : 1)
  return new Date(now.setDate(diff))
}

const scheduleDesktopReminder = (taskName: string, durationMinutes: number, mode: PomodoroMode) => {
  void setPomodoroReminder({
    taskName,
    dueAt: Date.now() + durationMinutes * 60 * 1000,
    mode,
  }).catch(() => undefined)
}

const clearDesktopReminder = () => {
  void clearPomodoroReminder().catch(() => undefined)
}

export const usePomodoroStore = create<PomodoroState>()(
  persist(
    (set, get) => ({
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

      startTimer: (taskName: string, duration: number, taskId?: number | null) => {
        const now = Date.now()
        const nextDuration = Math.max(1, Math.min(120, Math.floor(duration)))
        set({
          isRunning: true,
          isPaused: false,
          remainingTime: nextDuration * 60,
          currentTask: taskName,
          currentTaskId: taskId ?? null,
          duration: nextDuration,
          focusDuration: nextDuration,
          timerMode: 'focus',
          currentBackendId: null,
          startedAt: now,
          pausedAt: null,
          pausedTotalMs: 0,
        })
        scheduleDesktopReminder(taskName, nextDuration, 'focus')

        // Fire-and-forget API call
        pomodoroApi.startPomodoro(taskName, nextDuration, taskId)
          .then((res) => {
            set({ currentBackendId: res.id, backendOnline: true })
          })
          .catch(() => set({ backendOnline: false }))
      },

      startBreakTimer: (durationOverride?: number) => {
        const now = Date.now()
        const { breakDuration } = get()
        const nextDuration = Math.max(1, Math.min(60, Math.floor(durationOverride ?? breakDuration)))
        set({
          isRunning: true,
          isPaused: false,
          remainingTime: nextDuration * 60,
          currentTask: '休息',
          currentTaskId: null,
          duration: nextDuration,
          timerMode: 'break',
          currentBackendId: null,
          startedAt: now,
          pausedAt: null,
          pausedTotalMs: 0,
        })
        scheduleDesktopReminder('休息', nextDuration, 'break')
      },

      setBreakDuration: (duration: number) => {
        const nextDuration = Math.max(1, Math.min(60, Math.floor(duration)))
        set({ breakDuration: nextDuration })
      },

      pauseTimer: () => {
        const now = Date.now()
        set({ isRunning: false, isPaused: true, pausedAt: now })
        clearDesktopReminder()
      },

      resumeTimer: () => {
        const { pausedAt, pausedTotalMs, remainingTime, currentTask, timerMode } = get()
        const now = Date.now()
        const nextPausedTotalMs = pausedAt ? pausedTotalMs + (now - pausedAt) : pausedTotalMs
        set({ isRunning: true, isPaused: false, pausedAt: null, pausedTotalMs: nextPausedTotalMs })
        scheduleDesktopReminder(currentTask || (timerMode === 'break' ? '休息' : '专注学习'), Math.max(1 / 60, remainingTime / 60), timerMode)
      },

      completeTimer: (actualSecondsOverride?: number, options?: { startBreak?: boolean }) => {
        const { currentTask, currentTaskId, duration, focusDuration, currentBackendId, startedAt, pausedTotalMs, timerMode, breakDuration } = get()
        if (timerMode === 'break') {
          clearDesktopReminder()
          set({
            isRunning: false,
            isPaused: false,
            remainingTime: focusDuration * 60,
            currentTask: '',
            currentTaskId: null,
            duration: focusDuration,
            timerMode: 'focus',
            currentBackendId: null,
            startedAt: null,
            pausedAt: null,
            pausedTotalMs: 0,
          })
          return
        }

        const totalSeconds = duration * 60
        const now = Date.now()
        const elapsedMs = startedAt ? Math.max(0, now - startedAt - pausedTotalMs) : totalSeconds * 1000
        const elapsedSeconds = Math.floor(elapsedMs / 1000)
        const actualSeconds = Math.max(0, Math.min(totalSeconds, actualSecondsOverride ?? elapsedSeconds))
        const rawMinutes = actualSeconds / 60
        const actualMinutes = Math.max(0.1, Math.round(rawMinutes * 10) / 10)

        // Add local record immediately (optimistic)
        if (currentTask) {
          const now = new Date()
          const newRecord: PomodoroRecord = {
            id: `${Date.now()}-${Math.random().toString(36).substr(2, 9)}`,
            backendId: currentBackendId ?? undefined,
            taskId: currentTaskId,
            taskName: currentTask,
            duration: actualMinutes,
            completedAt: now.toISOString(),
            date: getDateString(now),
            synced: false,
          }
          set((state) => ({
            records: [newRecord, ...state.records].slice(0, MAX_RECORDS),
          }))

          // Sync to backend
          if (currentBackendId) {
            pomodoroApi.completePomodoro(currentBackendId, true, undefined, actualMinutes).then((res) => {
              // Mark as synced
              set((state) => ({
                records: state.records.map((r) =>
                  r.id === newRecord.id ? { ...r, synced: true, backendId: res.id } : r
                ),
                backendOnline: true,
              }))
            }).catch(() => set({ backendOnline: false }))
          } else {
            // No backendId — try to create a completed record directly via batch
            pomodoroApi.batchCreatePomodoros(
              [{ task_name: currentTask, duration: actualMinutes, task_id: currentTaskId ?? null }],
              [now.toISOString()]
            ).then((res) => {
              if (res.ids.length > 0) {
                set((state) => ({
                  records: state.records.map((r) =>
                    r.id === newRecord.id ? { ...r, synced: true, backendId: res.ids[0] } : r
                  ),
                  backendOnline: true,
                }))
              } else {
                set({ backendOnline: false })
              }
            }).catch(() => set({ backendOnline: false }))
          }
        }

        if (options?.startBreak === false) {
          clearDesktopReminder()
          set({
            isRunning: false,
            isPaused: false,
            remainingTime: focusDuration * 60,
            currentTask: '',
            currentTaskId: null,
            duration: focusDuration,
            timerMode: 'focus',
            currentBackendId: null,
            startedAt: null,
            pausedAt: null,
            pausedTotalMs: 0,
          })
          return
        }

        get().startBreakTimer(breakDuration)
      },

      resetTimer: (durationOverride?: number) => {
        clearDesktopReminder()
        const { focusDuration } = get()
        const nextDuration = durationOverride !== undefined
          ? Math.max(1, Math.min(120, Math.floor(durationOverride)))
          : focusDuration
        set({
          isRunning: false,
          isPaused: false,
          remainingTime: nextDuration * 60,
          duration: nextDuration,
          focusDuration: nextDuration,
          timerMode: 'focus',
          currentTask: '',
          currentTaskId: null,
          currentBackendId: null,
          startedAt: null,
          pausedAt: null,
          pausedTotalMs: 0,
        })
      },

      tick: () => {
        const { duration, startedAt, pausedTotalMs, completeTimer } = get()
        if (!startedAt) return
        const now = Date.now()
        const totalSeconds = duration * 60
        const elapsedMs = Math.max(0, now - startedAt - pausedTotalMs)
        const elapsedSeconds = Math.floor(elapsedMs / 1000)
        const remainingTime = Math.max(totalSeconds - elapsedSeconds, 0)
        if (remainingTime <= 0) {
          completeTimer(totalSeconds)
        } else {
          set({ remainingTime })
        }
      },

      addRecord: (taskName: string, duration: number) => {
        const now = new Date()
        const newRecord: PomodoroRecord = {
          id: `${Date.now()}-${Math.random().toString(36).substr(2, 9)}`,
          taskName,
          duration,
          completedAt: now.toISOString(),
          date: getDateString(now),
          synced: false,
        }
        set((state) => ({
          records: [newRecord, ...state.records].slice(0, MAX_RECORDS),
        }))
      },

      setBackgroundImage: (backgroundImage: string | null) => {
        set({ backgroundImage })
        void setDesktopPreference<PomodoroBackgroundPreference>(
          POMODORO_BACKGROUND_PREFERENCE_KEY,
          { backgroundImage },
        )
      },

      loadBackgroundImagePreference: async () => {
        const desktopPreference = normalizePomodoroBackgroundPreference(
          await getDesktopPreference<PomodoroBackgroundPreference>(POMODORO_BACKGROUND_PREFERENCE_KEY),
        )

        if (desktopPreference) {
          set({ backgroundImage: desktopPreference.backgroundImage })
          return
        }

        void setDesktopPreference<PomodoroBackgroundPreference>(
          POMODORO_BACKGROUND_PREFERENCE_KEY,
          { backgroundImage: get().backgroundImage },
        )
      },

      syncPendingRecords: async () => {
        const { records } = get()
        const pending = records.filter((r) => r.synced === false)
        if (pending.length === 0) return

        const res = await pomodoroApi.batchCreatePomodoros(
          pending.map((r) => ({ task_name: r.taskName, duration: r.duration, task_id: r.taskId ?? null })),
          pending.map((r) => r.completedAt)
        )

        if (res && res.ids.length === pending.length) {
          set((state) => {
            const pendingIds = new Set(pending.map((r) => r.id))
            return {
              records: state.records.map((r) => {
                if (!pendingIds.has(r.id)) return r
                const idx = pending.findIndex((p) => p.id === r.id)
                return { ...r, synced: true, backendId: res.ids[idx] }
              }),
              backendOnline: true,
            }
          })
        } else {
          set({ backendOnline: false })
        }
      },

      migrateLocalRecords: async () => {
        const { records, migrated } = get()
        if (migrated) return

        // Find old records that have no synced flag (pre-integration data)
        const oldRecords = records.filter((r) => r.synced === undefined)
        if (oldRecords.length === 0) {
          set({ migrated: true })
          return
        }

        const res = await pomodoroApi.batchCreatePomodoros(
          oldRecords.map((r) => ({ task_name: r.taskName, duration: r.duration, task_id: r.taskId ?? null })),
          oldRecords.map((r) => r.completedAt)
        )

        if (res && res.ids.length === oldRecords.length) {
          set((state) => {
            const oldIds = new Set(oldRecords.map((r) => r.id))
            return {
              records: state.records.map((r) => {
                if (!oldIds.has(r.id)) return r
                const idx = oldRecords.findIndex((o) => o.id === r.id)
                return { ...r, synced: true, backendId: res.ids[idx] }
              }),
              migrated: true,
              backendOnline: true,
            }
          })
        } else {
          set({ backendOnline: false })
        }
      },

      refreshRecordsFromBackend: async () => {
        try {
          const recent = await pomodoroApi.getRecentPomodoros(BACKEND_REFRESH_LIMIT)
          const completedRecords = recent
            .filter((p) => p.completed && p.ended_at)
            .map((p) => toRecord(p))
            .filter((record): record is PomodoroRecord => record !== null)

          const activeTimer = recent.find((p) => !p.completed && !p.ended_at)
          const activeState: Partial<PomodoroState> = {}
          const expiredRecords: PomodoroRecord[] = []

          if (activeTimer) {
            const startedAt = parseTimestamp(activeTimer.started_at)
            const durationMinutes = Math.max(0.1, Number(activeTimer.duration) || 25)
            const totalSeconds = Math.max(1, Math.round(durationMinutes * 60))

            if (Number.isFinite(startedAt)) {
              const elapsedSeconds = Math.max(0, Math.floor((Date.now() - startedAt) / 1000))
              const remainingSeconds = Math.max(totalSeconds - elapsedSeconds, 0)

              if (remainingSeconds > 0) {
                const taskName = activeTimer.task_name?.trim() || '专注学习'
                Object.assign(activeState, {
                  isRunning: true,
                  isPaused: false,
                  remainingTime: remainingSeconds,
                  currentTask: taskName,
                  currentTaskId: activeTimer.task_id,
                  duration: durationMinutes,
                  focusDuration: durationMinutes,
                  timerMode: 'focus',
                  currentBackendId: activeTimer.id,
                  startedAt,
                  pausedAt: null,
                  pausedTotalMs: 0,
                })
                scheduleDesktopReminder(taskName, remainingSeconds / 60, 'focus')
              } else if ((Date.now() - startedAt - totalSeconds * 1000) <= ACTIVE_TIMER_STALE_GRACE_MS) {
                const completedAt = new Date(startedAt + totalSeconds * 1000).toISOString()
                const completedRecord = toRecord(activeTimer, completedAt)
                if (completedRecord) {
                  expiredRecords.push(completedRecord)
                }
                Object.assign(activeState, {
                  isRunning: false,
                  isPaused: false,
                  remainingTime: totalSeconds,
                  currentTask: '',
                  currentTaskId: null,
                  duration: durationMinutes,
                  focusDuration: durationMinutes,
                  timerMode: 'focus',
                  currentBackendId: null,
                  startedAt: null,
                  pausedAt: null,
                  pausedTotalMs: 0,
                })

                await pomodoroApi.completePomodoro(activeTimer.id, true, undefined, durationMinutes)
              }
            }
          }

          set((state) => ({
            records: mergeRecords([...expiredRecords, ...completedRecords], state.records),
            backendOnline: true,
            ...activeState,
          }))
        } catch {
          set({ backendOnline: false })
        }
      },

      getTodayRecords: () => {
        const today = getDateString()
        return get().records.filter((r) => r.date === today)
      },

      getWeekRecords: () => {
        const weekStart = getDateString(getWeekStart())
        return get().records.filter((r) => r.date >= weekStart)
      },

      getStats: () => {
        const today = getDateString()
        const weekStart = getDateString(getWeekStart())
        const records = get().records

        const todayRecords = records.filter((r) => r.date === today)
        const weekRecords = records.filter((r) => r.date >= weekStart)

        // Generate weekly data for chart
        const weeklyData: { date: string; count: number; minutes: number }[] = []
        const weekStartDate = getWeekStart()

        for (let i = 0; i < 7; i++) {
          const date = new Date(weekStartDate)
          date.setDate(date.getDate() + i)
          const dateStr = getDateString(date)
          const dayRecords = records.filter((r) => r.date === dateStr)
          weeklyData.push({
            date: dateStr,
            count: dayRecords.length,
            minutes: dayRecords.reduce((sum, r) => sum + r.duration, 0),
          })
        }

        return {
          todayCount: todayRecords.length,
          todayMinutes: todayRecords.reduce((sum, r) => sum + r.duration, 0),
          weekCount: weekRecords.length,
          weekMinutes: weekRecords.reduce((sum, r) => sum + r.duration, 0),
          weeklyData,
        }
      },

      // 按时间范围筛选记录
      getRecordsByRange: (range: DateRange) => {
        const records = get().records
        const today = getDateString()

        switch (range) {
          case 'day':
            return records.filter((r) => r.date === today)
          case 'week':
            const weekStart = getDateString(getWeekStart())
            return records.filter((r) => r.date >= weekStart)
          case 'month':
            const monthStart = today.substring(0, 7) + '-01'
            return records.filter((r) => r.date >= monthStart)
          case 'all':
          default:
            return records
        }
      },

      // 按任务分组统计时长分布（饼图数据）
      getTaskDistribution: (range: DateRange) => {
        const records = get().getRecordsByRange(range)

        // 按任务名分组统计
        const taskMap = new Map<string, { minutes: number; count: number }>()
        for (const r of records) {
          const existing = taskMap.get(r.taskName) || { minutes: 0, count: 0 }
          taskMap.set(r.taskName, {
            minutes: existing.minutes + r.duration,
            count: existing.count + 1,
          })
        }

        // 计算总时长
        const totalMinutes = records.reduce((sum, r) => sum + r.duration, 0)

        // 饼图颜色调色板（macOS 风格）
        const colors = [
          '#007AFF', // 蓝色
          '#34C759', // 绿色
          '#FF9500', // 橙色
          '#AF52DE', // 紫色
          '#FF2D55', // 粉色
          '#5AC8FA', // 浅蓝
          '#FFCC00', // 黄色
          '#FF3B30', // 红色
          '#5856D6', // 靛蓝
          '#00C7BE', // 青色
        ]

        // 转换为数组并排序（按时长降序）
        const result: TaskDistributionItem[] = Array.from(taskMap.entries())
          .map(([taskName, data], index) => ({
            taskName,
            minutes: data.minutes,
            count: data.count,
            percentage: totalMinutes > 0 ? Math.round((data.minutes / totalMinutes) * 1000) / 10 : 0,
            color: colors[index % colors.length],
          }))
          .sort((a, b) => b.minutes - a.minutes)

        return result
      },

      // 累计统计
      getCumulativeStats: () => {
        const records = get().records

        if (records.length === 0) {
          return {
            totalCount: 0,
            totalMinutes: 0,
            totalHours: 0,
            dailyAverageMinutes: 0,
            firstRecordDate: null,
            activeDays: 0,
          }
        }

        const totalMinutes = records.reduce((sum, r) => sum + r.duration, 0)

        // 统计有记录的独立天数
        const uniqueDays = new Set(records.map((r) => r.date))
        const activeDays = uniqueDays.size

        // 找到最早的记录日期
        const sortedDates = Array.from(uniqueDays).sort()
        const firstRecordDate = sortedDates[0] || null

        return {
          totalCount: records.length,
          totalMinutes,
          totalHours: Math.round(totalMinutes / 60 * 10) / 10,
          dailyAverageMinutes: activeDays > 0 ? Math.round((totalMinutes / activeDays) * 10) / 10 : 0,
          firstRecordDate,
          activeDays,
        }
      },
    }),
    {
      name: 'pomodoro-storage',
      partialize: (state) => ({
        isRunning: state.isRunning,
        isPaused: state.isPaused,
        remainingTime: state.remainingTime,
        currentTask: state.currentTask,
        currentTaskId: state.currentTaskId,
        duration: state.duration,
        timerMode: state.timerMode,
        currentBackendId: state.currentBackendId,
        startedAt: state.startedAt,
        pausedAt: state.pausedAt,
        pausedTotalMs: state.pausedTotalMs,
        backgroundImage: state.backgroundImage,
        records: state.records,
        migrated: state.migrated,
        focusDuration: state.focusDuration,
        breakDuration: state.breakDuration,
      }),
    }
  )
)
