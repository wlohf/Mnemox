import { useEffect } from 'react'
import { usePomodoroStore } from '../stores/pomodoroStore'

export function PomodoroTicker() {
  const isRunning = usePomodoroStore((s) => s.isRunning)
  const isPaused = usePomodoroStore((s) => s.isPaused)
  const tick = usePomodoroStore((s) => s.tick)

  useEffect(() => {
    if (!isRunning || isPaused) return
    tick()
    const timer = window.setInterval(tick, 1000)
    return () => window.clearInterval(timer)
  }, [isRunning, isPaused, tick])

  useEffect(() => {
    const handleVisibilityChange = () => {
      if (!document.hidden) {
        tick()
      }
    }
    document.addEventListener('visibilitychange', handleVisibilityChange)
    window.addEventListener('focus', tick)
    return () => {
      document.removeEventListener('visibilitychange', handleVisibilityChange)
      window.removeEventListener('focus', tick)
    }
  }, [tick])

  return null
}
