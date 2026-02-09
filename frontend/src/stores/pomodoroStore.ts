import { create } from 'zustand'
import { persist } from 'zustand/middleware'

export interface PomodoroRecord {
  id: string
  taskName: string
  duration: number // in minutes
  completedAt: string // ISO date string
  date: string // YYYY-MM-DD format for easy grouping
}

interface PomodoroStats {
  todayCount: number
  todayMinutes: number
  weekCount: number
  weekMinutes: number
  weeklyData: { date: string; count: number; minutes: number }[]
}

interface PomodoroState {
  // Current timer state
  isRunning: boolean
  isPaused: boolean
  remainingTime: number // in seconds
  currentTask: string
  duration: number // in minutes
  
  // Records
  records: PomodoroRecord[]
  
  // Actions
  startTimer: (taskName: string, duration: number) => void
  pauseTimer: () => void
  resumeTimer: () => void
  completeTimer: () => void
  resetTimer: () => void
  tick: () => void
  addRecord: (taskName: string, duration: number) => void
  
  // Stats
  getStats: () => PomodoroStats
  getTodayRecords: () => PomodoroRecord[]
  getWeekRecords: () => PomodoroRecord[]
}

const getDateString = (date: Date = new Date()) => {
  return date.toISOString().split('T')[0]
}

const getWeekStart = () => {
  const now = new Date()
  const dayOfWeek = now.getDay()
  const diff = now.getDate() - dayOfWeek + (dayOfWeek === 0 ? -6 : 1)
  return new Date(now.setDate(diff))
}

export const usePomodoroStore = create<PomodoroState>()(
  persist(
    (set, get) => ({
      isRunning: false,
      isPaused: false,
      remainingTime: 25 * 60,
      currentTask: '',
      duration: 25,
      records: [],

      startTimer: (taskName: string, duration: number) => {
        set({
          isRunning: true,
          isPaused: false,
          remainingTime: duration * 60,
          currentTask: taskName,
          duration,
        })
      },

      pauseTimer: () => {
        set({ isRunning: false, isPaused: true })
      },

      resumeTimer: () => {
        set({ isRunning: true, isPaused: false })
      },

      completeTimer: () => {
        const { currentTask, duration, addRecord } = get()
        if (currentTask) {
          addRecord(currentTask, duration)
        }
        set({
          isRunning: false,
          isPaused: false,
          remainingTime: duration * 60,
        })
      },

      resetTimer: () => {
        const { duration } = get()
        set({
          isRunning: false,
          isPaused: false,
          remainingTime: duration * 60,
        })
      },

      tick: () => {
        const { remainingTime, completeTimer } = get()
        if (remainingTime <= 1) {
          completeTimer()
        } else {
          set({ remainingTime: remainingTime - 1 })
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
        }
        set((state) => ({
          records: [newRecord, ...state.records].slice(0, 500), // Keep last 500 records
        }))
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
    }),
    {
      name: 'pomodoro-storage',
      partialize: (state) => ({ records: state.records }),
    }
  )
)
