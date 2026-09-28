import { useCallback, useEffect, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { savePlan, type PlanItem } from '../../services/planApi'
import { getApiErrorMessage } from '../../services/apiClient'

/*
 * One day's plan document. Edits apply locally at once and save after a short
 * pause (and on leave), so ticking a checkbox never needs a "save" click.
 */

export type SaveState = 'saved' | 'dirty' | 'saving' | 'error'

const AUTOSAVE_MS = 900

export function usePlanDoc(day: string, serverContent: string | undefined, rangeKey: readonly unknown[]) {
  const qc = useQueryClient()
  const [content, setContentState] = useState(serverContent ?? '')
  const [state, setState] = useState<SaveState>('saved')
  const [error, setError] = useState<string | null>(null)
  const timer = useRef<number | null>(null)
  const latest = useRef({ day, content: serverContent ?? '', dirty: false })

  // Switching day (or the server copy arriving) resets the document.
  useEffect(() => {
    if (latest.current.dirty && latest.current.day === day) return
    setContentState(serverContent ?? '')
    latest.current = { day, content: serverContent ?? '', dirty: false }
    setState('saved')
    setError(null)
  }, [day, serverContent])

  const flush = useCallback(async () => {
    if (timer.current) {
      window.clearTimeout(timer.current)
      timer.current = null
    }
    const snap = latest.current
    if (!snap.dirty) return true
    setState('saving')
    try {
      const saved = await savePlan(snap.day, snap.content)
      // Only clear dirty if nothing changed while saving.
      if (latest.current.day === snap.day && latest.current.content === snap.content) {
        latest.current = { ...latest.current, dirty: false }
        setState('saved')
      } else {
        setState('dirty')
      }
      qc.setQueryData<PlanItem[]>(rangeKey, prev => {
        const list = prev ?? []
        const next = { date: saved.date ?? snap.day, content: saved.content ?? snap.content }
        return list.some(p => p.date === next.date) ? list.map(p => (p.date === next.date ? next : p)) : [...list, next]
      })
      setError(null)
      return true
    } catch (e) {
      setState('error')
      setError(getApiErrorMessage(e, '保存失败'))
      return false
    }
  }, [qc, rangeKey])

  const setContent = useCallback(
    (next: string | ((prev: string) => string)) => {
      setContentState(prev => {
        const value = typeof next === 'function' ? next(prev) : next
        if (value !== prev) {
          latest.current = { day: latest.current.day, content: value, dirty: true }
          setState('dirty')
          if (timer.current) window.clearTimeout(timer.current)
          timer.current = window.setTimeout(() => void flush(), AUTOSAVE_MS)
        }
        return value
      })
    },
    [flush],
  )

  /** Replace content from the server (AI generation) without an extra save. */
  const replaceFromServer = useCallback((value: string) => {
    if (timer.current) window.clearTimeout(timer.current)
    latest.current = { day: latest.current.day, content: value, dirty: false }
    setContentState(value)
    setState('saved')
  }, [])

  // Save pending edits when the day changes or the page unmounts.
  useEffect(() => {
    return () => {
      if (latest.current.dirty) void flush()
    }
  }, [day, flush])

  useEffect(() => {
    const onBeforeUnload = (e: BeforeUnloadEvent) => {
      if (!latest.current.dirty) return
      void flush()
      e.preventDefault()
    }
    window.addEventListener('beforeunload', onBeforeUnload)
    return () => window.removeEventListener('beforeunload', onBeforeUnload)
  }, [flush])

  return { content, setContent, replaceFromServer, state, error, flush }
}
