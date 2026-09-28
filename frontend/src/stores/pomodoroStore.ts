import { create } from 'zustand'
import { createJSONStorage, persist } from 'zustand/middleware'
import * as pomodoroApi from '../services/pomodoroApi'
import type { PomodoroStartResponse } from '../services/pomodoroApi'
import { clearPomodoroReminder, setPomodoroReminder } from '../services/desktopReminder'
import { getDesktopPreference, setDesktopPreference } from '../services/desktopPreferences'
import { captureApiSession } from '../services/sessionScope'
import { getApiErrorMessage } from '../services/apiClient'

export interface PomodoroRecord {
  id: string
  backendId?: number
  taskId?: number | null
  taskName: string
  duration: number // in minutes
  completedAt: string // ISO date string
  date: string // YYYY-MM-DD format for easy grouping
  synced?: boolean
  completed?: boolean
  note?: string | null
  stopReason?: pomodoroApi.StopReason | null
  startedAt?: string
  plannedDuration?: number
  coachActionAttemptId?: string | null
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
  currentCoachActionAttemptId: string | null
  currentStartRequestKey: string | null
  startedAt: number | null
  pausedAt: number | null
  pausedTotalMs: number
  backgroundImage: string | null

  // Records
  records: PomodoroRecord[]

  // Sync state
  backendOnline: boolean
  migrated: boolean
  lastSyncError: string | null

  // Actions
  startTimer: (taskName: string, duration: number, taskId?: number | null, coachActionAttemptId?: string | null) => void
  startBreakTimer: (durationOverride?: number) => void
  setBreakDuration: (duration: number) => void
  pauseTimer: () => void
  resumeTimer: () => void
  completeTimer: (actualSeconds?: number, options?: { startBreak?: boolean; completed?: boolean; note?: string; stopReason?: 'early_done' | 'interrupted' | 'distracted' }) => void
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
export const POMODORO_BACKGROUND_PREFERENCE_KEY = 'pomodoro.background'
let accountGeneration = 0
let accountUserId: number | null = null
let accountStorageId = 'anonymous'
let syncFlight: Promise<void> | null = null
const accountScope = () => {
  const generation = accountGeneration
  const session = captureApiSession()
  return { session, current: () => generation === accountGeneration && !session.signal.aborted }
}
const backgroundKey = () => `${POMODORO_BACKGROUND_PREFERENCE_KEY}:${accountStorageId}`
const trimRecords = (records: PomodoroRecord[]) => [
  ...records.filter(r => r.synced !== true),
  ...records.filter(r => r.synced === true).slice(0, MAX_RECORDS),
]

const emptyTimer = {
  isRunning: false, isPaused: false, remainingTime: 1500, currentTask: '', currentTaskId: null,
  duration: 25, focusDuration: 25, breakDuration: 5, timerMode: 'focus' as PomodoroMode,
  currentBackendId: null, currentCoachActionAttemptId: null, currentStartRequestKey: null,
  startedAt: null, pausedAt: null, pausedTotalMs: 0,
}

export async function switchPomodoroAccount(userId: number | null, createdAt?: string) {
  ++accountGeneration
  accountUserId = null // Reset must never overwrite the previous account's persisted state.
  syncFlight = null
  clearDesktopReminder()
  usePomodoroStore.setState({ ...emptyTimer, records: [], backgroundImage: null,
    migrated: false, backendOnline: false, lastSyncError: null })
  accountStorageId = createdAt ? `${userId}:${encodeURIComponent(createdAt)}` : String(userId)
  usePomodoroStore.persist.setOptions({ name: `pomodoro-storage:user:${accountStorageId}` })
  accountUserId = userId
  if (userId !== null) await usePomodoroStore.persist.rehydrate()
}


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
  const normalized = /(?:Z|[+-]\d{2}:\d{2})$/i.test(value) ? value : `${value}Z`
  return new Date(normalized).getTime()
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

const mergeRecords = (backendRecords: PomodoroRecord[], localRecords: PomodoroRecord[]) => {
  const ids = new Set<string>(), backendIds = new Set<number>()
  const merged: PomodoroRecord[] = []
  for (const record of [...localRecords.filter(r => r.synced !== true), ...backendRecords, ...localRecords]) {
    if (ids.has(record.id) || (record.backendId !== undefined && backendIds.has(record.backendId))) continue
    ids.add(record.id)
    if (record.backendId !== undefined) backendIds.add(record.backendId)
    merged.push(record)
  }
  return trimRecords(sortRecordsByCompletedAt(merged))
}

const toRecord = (pomodoro: PomodoroStartResponse, completedAtOverride?: string): PomodoroRecord | null => {
  const completedAt = completedAtOverride ?? pomodoro.ended_at
  if (!completedAt) return null

  return {
    id: pomodoro.client_record_id || `backend-${pomodoro.id}`,
    completed: pomodoro.completed, stopReason: pomodoro.stop_reason, note: pomodoro.note,
    startedAt: pomodoro.started_at, coachActionAttemptId: pomodoro.coach_action_attempt_id,
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
      currentCoachActionAttemptId: null,
      currentStartRequestKey: null,
      startedAt: null,
      pausedAt: null,
      pausedTotalMs: 0,
      backgroundImage: null,
      records: [],
      backendOnline: false,
      migrated: false,
      lastSyncError: null,

      startTimer: (taskName: string, duration: number, taskId?: number | null, coachActionAttemptId?: string | null) => {
        if (get().isRunning || get().isPaused) return
        const now = Date.now()
        const nextDuration = Math.max(1, Math.min(120, Math.floor(duration)))
        const scope = accountScope()
        const startRequestKey = crypto.randomUUID()
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
          currentCoachActionAttemptId: coachActionAttemptId ?? null,
          currentStartRequestKey: startRequestKey,
          startedAt: now,
          pausedAt: null,
          pausedTotalMs: 0,
        })
        scheduleDesktopReminder(taskName, nextDuration, 'focus')

        void pomodoroApi.startPomodoro(taskName, nextDuration, taskId, coachActionAttemptId,
          startRequestKey, new Date(now).toISOString(), scope.session)
          .then((res) => {
            if (!scope.current()) return
            set((state) => ({
              ...(state.currentStartRequestKey === startRequestKey ? { currentBackendId: res.id } : {}),
              records: state.records.map(r => r.id === startRequestKey ? { ...r, backendId: res.id } : r),
              backendOnline: true,
            }))
          })
          .catch(() => { if (scope.current()) set({ backendOnline: false }) })
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
          currentCoachActionAttemptId: null,
          currentStartRequestKey: null,
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
        const before = get()
        if (!before.isRunning || before.isPaused) return
        get().tick()
        if (!get().isRunning || get().startedAt !== before.startedAt || get().timerMode !== before.timerMode) return
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

      completeTimer: (
        actualSecondsOverride?: number,
        options?: { startBreak?: boolean; completed?: boolean; note?: string; stopReason?: 'early_done' | 'interrupted' | 'distracted' },
      ) => {
        const {
          currentTask,
          currentTaskId,
          duration,
          focusDuration,
          currentBackendId,
          currentStartRequestKey,
          currentCoachActionAttemptId,
          startedAt,
          pausedTotalMs,
          pausedAt,
          timerMode,
          breakDuration,
        } = get()
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
            currentCoachActionAttemptId: null,
            currentStartRequestKey: null,
            startedAt: null,
            pausedAt: null,
            pausedTotalMs: 0,
          })
          return
        }

        const totalSeconds = duration * 60
        const now = Date.now()
        const elapsedMs = startedAt ? Math.max(0, (pausedAt ?? now) - startedAt - pausedTotalMs) : totalSeconds * 1000
        const elapsedSeconds = Math.floor(elapsedMs / 1000)
        const actualSeconds = Math.max(0, Math.min(totalSeconds, actualSecondsOverride ?? elapsedSeconds))
        const rawMinutes = actualSeconds / 60
        const actualMinutes = Math.max(0.1, Math.round(rawMinutes * 10) / 10)

        // Add local record immediately (optimistic)
        if (currentTask) {
          const now = new Date()
          const newRecord: PomodoroRecord = {
            id: currentStartRequestKey || crypto.randomUUID(),
            completed: options?.completed ?? true, stopReason: options?.stopReason, note: options?.note,
            startedAt: startedAt ? new Date(startedAt).toISOString() : undefined,
            plannedDuration: duration, coachActionAttemptId: currentCoachActionAttemptId,
            backendId: currentBackendId ?? undefined,
            taskId: currentTaskId,
            taskName: currentTask,
            duration: actualMinutes,
            completedAt: now.toISOString(),
            date: getDateString(now),
            synced: false,
          }
          set((state) => ({
            records: trimRecords([newRecord, ...state.records]),
          }))

          void get().syncPendingRecords()
        }

        if (options?.startBreak === false || options?.completed === false) {
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
            currentCoachActionAttemptId: null,
            currentStartRequestKey: null,
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
          currentCoachActionAttemptId: null,
          currentStartRequestKey: null,
          startedAt: null,
          pausedAt: null,
          pausedTotalMs: 0,
        })
      },

      tick: () => {
        const { duration, startedAt, pausedTotalMs, completeTimer, isRunning, isPaused } = get()
        if (!startedAt || !isRunning || isPaused) return
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
          id: crypto.randomUUID(),
          completed: true,
          taskName,
          duration,
          completedAt: now.toISOString(),
          date: getDateString(now),
          synced: false,
        }
        set((state) => ({
          records: trimRecords([newRecord, ...state.records]),
        }))
      },

      setBackgroundImage: (backgroundImage: string | null) => {
        set({ backgroundImage })
        void setDesktopPreference<PomodoroBackgroundPreference>(
          backgroundKey(),
          { backgroundImage },
        )
      },

      loadBackgroundImagePreference: async () => {
        const scope = accountScope()
        const desktopPreference = normalizePomodoroBackgroundPreference(
          await getDesktopPreference<PomodoroBackgroundPreference>(backgroundKey()),
        )

        if (!scope.current()) return
        if (desktopPreference) {
          set({ backgroundImage: desktopPreference.backgroundImage })
          return
        }

        void setDesktopPreference<PomodoroBackgroundPreference>(
          backgroundKey(),
          { backgroundImage: get().backgroundImage },
        )
      },

      syncPendingRecords: async () => {
        if (syncFlight) return syncFlight
        const scope = accountScope()
        const run = async () => {
          try {
            while (scope.current()) {
              const pending = get().records.filter(r => r.synced !== true).slice(0, 500)
              if (!pending.length) return
              const res = await pomodoroApi.batchCreatePomodoros(pending.map(r => ({
                task_name: r.taskName, duration: r.duration, task_id: r.taskId ?? null,
                client_record_id: r.id, backend_id: r.backendId, started_at: r.startedAt,
                completed: r.completed ?? true, stop_reason: r.stopReason, note: r.note,
                planned_duration: r.plannedDuration, coach_action_attempt_id: r.coachActionAttemptId,
              })), pending.map(r => r.completedAt), scope.session)
              if (!scope.current()) return
              if (res.ids.length !== pending.length) throw new Error('同步结果不完整，原记录已保留')
              const syncedIds = new Map(pending.map((r, i) => [r.id, res.ids[i]]))
              set(state => ({ records: trimRecords(state.records.map(r => syncedIds.has(r.id)
                ? { ...r, synced: true, backendId: syncedIds.get(r.id) } : r)),
                backendOnline: true, lastSyncError: null }))
            }
          } catch (error) {
            if (scope.current()) set({ backendOnline: false,
              lastSyncError: getApiErrorMessage(error, '同步失败，记录已保留，联网后可重试') })
          }
        }
        const flight = run().finally(() => { if (syncFlight === flight) syncFlight = null })
        syncFlight = flight
        return flight
      },

      migrateLocalRecords: async () => {
        const scope = accountScope()
        await get().syncPendingRecords()
        if (scope.current()) set({ migrated: get().records.every(r => r.synced === true) })
      },

      refreshRecordsFromBackend: async () => {
        const scope = accountScope()
        try {
          const recent = await pomodoroApi.getRecentPomodoros(BACKEND_REFRESH_LIMIT, scope.session)
          if (!scope.current()) return
          const endedRecords = recent.filter(p => p.ended_at).map(p => toRecord(p))
            .filter((r): r is PomodoroRecord => r !== null)
          const active = recent.find(p => !p.ended_at && p.time_basis !== 'legacy' && p.time_basis !== 'mixed')
          const ownsTimer = get().startedAt !== null
          const activeState: Partial<PomodoroState> = {}
          if (active && !ownsTimer) {
            const start = parseTimestamp(active.started_at)
            if (Number.isFinite(start)) {
              const remaining = Math.max(0, Math.round(active.duration * 60 - (Date.now() - start) / 1000))
              Object.assign(activeState, { ...emptyTimer,
                isRunning: remaining > 0, isPaused: remaining === 0, remainingTime: remaining,
                currentTask: active.task_name || '专注学习', currentTaskId: active.task_id,
                duration: active.duration, focusDuration: active.duration,
                currentBackendId: active.id, currentStartRequestKey: active.client_record_id ?? null,
                currentCoachActionAttemptId: active.coach_action_attempt_id ?? null,
                startedAt: start, pausedAt: remaining === 0 ? Date.now() : null,
              })
              // Expired server records require an explicit outcome; wall time alone
              // is not evidence of completed focus (the other device may be paused).
              if (remaining > 0) scheduleDesktopReminder(active.task_name || '专注学习', remaining / 60, 'focus')
            }
          }
          set(state => ({ records: mergeRecords(endedRecords, state.records), backendOnline: true, ...activeState }))
        } catch (error) {
          if (scope.current()) set({ backendOnline: false, lastSyncError: getApiErrorMessage(error, '刷新失败') })
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
            count: dayRecords.filter(r => r.completed !== false).length,
            minutes: dayRecords.reduce((sum, r) => sum + r.duration, 0),
          })
        }

        return {
          todayCount: todayRecords.filter(r => r.completed !== false).length,
          todayMinutes: todayRecords.reduce((sum, r) => sum + r.duration, 0),
          weekCount: weekRecords.filter(r => r.completed !== false).length,
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
          totalCount: records.filter(r => r.completed !== false).length,
          totalMinutes,
          totalHours: Math.round(totalMinutes / 60 * 10) / 10,
          dailyAverageMinutes: activeDays > 0 ? Math.round((totalMinutes / activeDays) * 10) / 10 : 0,
          firstRecordDate,
          activeDays,
        }
      },
    }),
    {
      name: 'pomodoro-storage:anonymous',
      skipHydration: true,
      storage: createJSONStorage(() => ({
        getItem: key => accountUserId === null ? null : localStorage.getItem(key),
        setItem: (key, value) => { if (accountUserId !== null) localStorage.setItem(key, value) },
        removeItem: key => { if (accountUserId !== null) localStorage.removeItem(key) },
      })),
      partialize: (state) => ({
        isRunning: state.isRunning,
        isPaused: state.isPaused,
        remainingTime: state.remainingTime,
        currentTask: state.currentTask,
        currentTaskId: state.currentTaskId,
        duration: state.duration,
        timerMode: state.timerMode,
        currentBackendId: state.currentBackendId,
        currentStartRequestKey: state.currentStartRequestKey,
        currentCoachActionAttemptId: state.currentCoachActionAttemptId,
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
