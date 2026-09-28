import { useEffect, useState } from 'react'

/**
 * Polls /health until the backend answers. The desktop shell starts the
 * backend alongside the window, so first paint can precede the API.
 */
export function useBackendReady(): { ready: boolean; attempts: number } {
  const [ready, setReady] = useState(false)
  const [attempts, setAttempts] = useState(0)

  useEffect(() => {
    if (ready) return
    let cancelled = false
    let timer = 0
    const poll = async (n: number) => {
      try {
        const res = await fetch('/health', { cache: 'no-store' })
        if (res.ok) {
          if (!cancelled) setReady(true)
          return
        }
      } catch {
        // backend not reachable yet
      }
      if (cancelled) return
      setAttempts(n + 1)
      timer = window.setTimeout(() => void poll(n + 1), n < 5 ? 1000 : 2500)
    }
    void poll(0)
    return () => {
      cancelled = true
      window.clearTimeout(timer)
    }
  }, [ready])

  return { ready, attempts }
}
