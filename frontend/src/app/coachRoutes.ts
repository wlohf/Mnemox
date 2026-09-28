import type { CoachActionAttempt } from '../services/coachApi'

/**
 * Carry a Coach action attempt through navigation so the destination page
 * (pomodoro / review / plans) can report the outcome against it.
 */
export function routeWithCoachAttempt(route: string, attempt: CoachActionAttempt, nudgeId: string): string {
  const url = new URL(route, window.location.origin)
  url.searchParams.set('coach_attempt', attempt.id)
  url.searchParams.set('coach_nudge', nudgeId)
  const minutes = Number(attempt.action_payload?.minutes)
  if (Number.isFinite(minutes) && minutes > 0) url.searchParams.set('coach_minutes', String(minutes))
  return `${url.pathname}${url.search}${url.hash}`
}

/** Only follow in-app routes coming from server payloads. */
export function safeInternalRoute(route: unknown): string | null {
  if (typeof route !== 'string') return null
  const trimmed = route.trim()
  if (!trimmed.startsWith('/') || trimmed.startsWith('//')) return null
  return trimmed
}
