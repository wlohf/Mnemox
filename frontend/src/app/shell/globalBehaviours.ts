import { useCallback, useEffect, useRef } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from '../../ui'
import { useAuthStore } from '../../stores/authStore'
import {
  evaluateCoach,
  getCoachPreferences,
  markCoachNudgeShown,
  recordCoachNudgeFeedback,
  startCoachNudgeAction,
  type CoachChannel,
  type CoachFeedbackOutcome,
  type CoachNudge,
} from '../../services/coachApi'
import {
  isDesktopCoachNotificationAvailable,
  onCoachNotificationRoute,
  showDesktopCoachNotification,
} from '../../services/desktopCoach'
import { getDailyIntervention } from '../../services/interventionApi'
import { dismissOnboarding, getOnboardingStatus, checkSystemUpdate } from '../../services/systemApi'
import { qk } from '../queryClient'
import { routeWithCoachAttempt, safeInternalRoute } from '../coachRoutes'
import { useShell } from './shellStore'

/*
 * App-wide behaviours that used to live inside the chat layout. They now run
 * once in the shell, whatever page the learner is on.
 */

const LEGACY_ONBOARDING_DISMISSED_PREFIX = 'mnemox_onboarding_dismissed_'

/* ---------------------------------------------------------------------------
   Coach nudges
--------------------------------------------------------------------------- */
export function useCoachNudges(ready: boolean) {
  const navigate = useNavigate()
  const { pathname } = useLocation()
  const qc = useQueryClient()
  const shown = useRef(new Set<string>())
  const prefs = useQuery({ queryKey: qk.coachPreferences, queryFn: getCoachPreferences, enabled: ready, staleTime: 5 * 60_000 })

  // Settings dialog writes this key after saving preferences.
  useEffect(() => {
    const onStorage = (e: StorageEvent) => {
      if (e.key === 'coach_preferences_updated') void qc.invalidateQueries({ queryKey: qk.coachPreferences })
    }
    window.addEventListener('storage', onStorage)
    return () => window.removeEventListener('storage', onStorage)
  }, [qc])

  const feedback = useCallback(async (nudge: CoachNudge, outcome: CoachFeedbackOutcome) => {
    const res = await recordCoachNudgeFeedback(nudge.id, { outcome })
    toast.dismiss(`coach-${nudge.id}`)
    if (res && (outcome === 'helpful' || outcome === 'accepted')) toast.success('已记录，教练会参考这次反馈')
    void qc.invalidateQueries({ queryKey: qk.coachNudges })
  }, [qc])

  const start = useCallback(async (nudge: CoachNudge) => {
    const started = await startCoachNudgeAction(nudge.id)
    toast.dismiss(`coach-${nudge.id}`)
    const route = safeInternalRoute(started?.nudge.route || nudge.route || nudge.suggested_action?.route)
    if (!started) {
      toast.error('暂时无法开始这条建议，请稍后再试')
      return
    }
    if (route) navigate(routeWithCoachAttempt(route, started.attempt, nudge.id))
  }, [navigate])

  const present = useCallback((nudge: CoachNudge | null) => {
    if (!nudge || shown.current.has(nudge.id)) return
    shown.current.add(nudge.id)
    void markCoachNudgeShown(nudge.id)
    const route = safeInternalRoute(nudge.route || nudge.suggested_action?.route)
    const inApp = () => {
      const signals = (nudge.explainability?.signals ?? []).slice(0, 2)
      toast.info(nudge.title, {
        id: `coach-${nudge.id}`,
        description: signals.length ? `${nudge.body}　依据：${signals.join('、')}` : nudge.body,
        duration: nudge.priority === 'high' ? 0 : 10000,
        actions: [
          ...(route ? [{ label: nudge.suggested_action?.label || '去处理', variant: 'primary' as const, onClick: () => void start(nudge) }] : []),
          { label: '稍后', variant: 'ghost', onClick: () => void feedback(nudge, 'later') },
          { label: '太打扰', variant: 'ghost', onClick: () => void feedback(nudge, 'too_disruptive') },
        ],
      })
    }
    if (nudge.channel === 'desktop_notification' && prefs.data?.desktop_notifications_enabled && isDesktopCoachNotificationAvailable()) {
      void showDesktopCoachNotification({ id: nudge.id, title: nudge.title, body: nudge.body, route: route || null })
        .then(ok => { if (!ok) inApp() })
        .catch(inApp)
      return
    }
    inApp()
  }, [feedback, prefs.data?.desktop_notifications_enabled, start])

  const evaluate = useCallback(async (
    eventType: string,
    payload: Record<string, unknown>,
    options: { source?: string; dedupeKey?: string; channel?: CoachChannel } = {},
  ) => {
    const result = await evaluateCoach({
      event: {
        event_type: eventType,
        source: options.source || 'frontend',
        channel: options.channel,
        payload,
        severity: 'info',
        dedupe_key: options.dedupeKey,
      },
      include_recent_notes: false,
      include_memories: true,
    })
    present(result?.nudge ?? null)
  }, [present])

  // Desktop notification click → start the attempt and route there.
  useEffect(() => {
    const unsubscribe = onCoachNotificationRoute(payload => {
      const route = safeInternalRoute(payload?.route)
      if (!route) return
      void startCoachNudgeAction(String(payload?.id || '')).then(started => {
        if (!started) navigate(route)
        else navigate(routeWithCoachAttempt(safeInternalRoute(started.nudge.route) || route, started.attempt, started.nudge.id))
      })
    })
    return () => unsubscribe?.()
  }, [navigate])

  // Returning to the app + scheduled proactive evaluation.
  const pathRef = useRef(pathname)
  pathRef.current = pathname
  useEffect(() => {
    if (!ready) return
    let lastFocus = 0
    const onFocus = () => {
      const now = Date.now()
      if (now - lastFocus < 30_000) return
      lastFocus = now
      void evaluate('app.inactive_returned', { path: pathRef.current }, { dedupeKey: `focus:${new Date().toISOString().slice(0, 13)}` })
    }
    window.addEventListener('focus', onFocus)
    const p = prefs.data
    const proactive = Boolean(p?.enabled && (p.proactive_enabled || p.desktop_notifications_enabled))
    const minutes = Math.max(30, p?.min_minutes_between_nudges || 60)
    const timer = proactive
      ? window.setInterval(() => {
          const desktop = Boolean(p?.desktop_notifications_enabled && isDesktopCoachNotificationAvailable())
          const slot = Math.floor(Date.now() / (minutes * 60_000))
          void evaluate('app.evaluate', { path: pathRef.current, scheduled: true }, {
            source: desktop ? 'desktop' : 'frontend',
            channel: desktop ? 'desktop_notification' : 'in_app_nudge',
            dedupeKey: `scheduled:${minutes}:${slot}`,
          })
        }, minutes * 60_000)
      : 0
    return () => {
      window.removeEventListener('focus', onFocus)
      if (timer) window.clearInterval(timer)
    }
  }, [evaluate, prefs.data, ready])

  return { evaluate, present }
}

/* ---------------------------------------------------------------------------
   Daily intervention reminder (in-app, rate-limited per 2h slot)
--------------------------------------------------------------------------- */
export function useDailyIntervention(ready: boolean) {
  const navigate = useNavigate()
  useEffect(() => {
    if (!ready) return
    const enabled = () => localStorage.getItem('intervention_enabled') !== 'false'
    const intervalMin = () => Math.max(5, Number.parseInt(localStorage.getItem('intervention_interval_min') || '30', 10) || 30)
    const check = async () => {
      if (!enabled()) return
      try {
        const report = await getDailyIntervention()
        if (!report?.should_push) return
        const slot = Math.floor(new Date().getHours() / 2)
        const key = `intervention_notified_${report.date}_slot${slot}`
        if (localStorage.getItem(key)) return
        localStorage.setItem(key, '1')
        const show = report.risk_level === 'high' ? toast.warning : toast.info
        show(report.push_title, {
          description: [report.push_body, ...report.suggestions.slice(0, 1)].join('　'),
          duration: report.risk_level === 'high' ? 0 : 9000,
          actions: [{ label: '查看详情', variant: 'primary', onClick: () => navigate('/eda?tab=intervention') }],
        })
      } catch {
        // Non-critical: a missing report never interrupts the learner.
      }
    }
    const first = window.setTimeout(() => void check(), 2500)
    let timer = window.setInterval(() => void check(), intervalMin() * 60_000)
    const onStorage = (e: StorageEvent) => {
      if (e.key !== 'intervention_enabled' && e.key !== 'intervention_interval_min') return
      window.clearInterval(timer)
      timer = window.setInterval(() => void check(), intervalMin() * 60_000)
    }
    window.addEventListener('storage', onStorage)
    return () => {
      window.clearTimeout(first)
      window.clearInterval(timer)
      window.removeEventListener('storage', onStorage)
    }
  }, [navigate, ready])
}

/* ---------------------------------------------------------------------------
   First-run onboarding (server-persisted "seen" flag)
--------------------------------------------------------------------------- */
export function useOnboardingAutoShow(ready: boolean) {
  const userId = useAuthStore(st => st.user?.id)
  const setOpen = useShell(st => st.setOnboardingOpen)
  const status = useQuery({ queryKey: qk.onboarding, queryFn: getOnboardingStatus, enabled: ready && !!userId, staleTime: 60_000 })
  const handled = useRef(false)
  useEffect(() => {
    const st = status.data
    if (!st || !userId || handled.current) return
    handled.current = true
    if (st.auto_show_seen) return
    const legacyDismissed = localStorage.getItem(`${LEGACY_ONBOARDING_DISMISSED_PREFIX}${userId}`) === 'true'
    void dismissOnboarding().catch(() => undefined)
    if (!legacyDismissed && st.stage !== 'loop_ready') setOpen(true)
  }, [setOpen, status.data, userId])
}

/* ---------------------------------------------------------------------------
   Update check (web + desktop share the backend manifest)
--------------------------------------------------------------------------- */
const UPDATE_AUTO_CHECK_KEY = 'sys_update_auto_check'
const UPDATE_INTERVAL_MIN_KEY = 'sys_update_interval_min'
const UPDATE_LAST_RESULT_KEY = 'sys_update_last'
const UPDATE_NOTIFIED_VERSION_KEY = 'sys_update_notified_version'

export function useUpdateCheck(authenticated: boolean) {
  useEffect(() => {
    if (!authenticated) return
    let destroyed = false
    let timer = 0
    const enabled = () => localStorage.getItem(UPDATE_AUTO_CHECK_KEY) !== 'false'
    const intervalMs = () => {
      const parsed = Number.parseInt(localStorage.getItem(UPDATE_INTERVAL_MIN_KEY) ?? '360', 10)
      const minutes = Number.isNaN(parsed) ? 360 : Math.min(Math.max(parsed, 5), 1440)
      return minutes * 60_000
    }
    const run = async () => {
      const result = await checkSystemUpdate().catch(() => null)
      if (destroyed || !result) return
      const payload = JSON.stringify(result)
      localStorage.setItem(UPDATE_LAST_RESULT_KEY, payload)
      window.dispatchEvent(new StorageEvent('storage', { key: UPDATE_LAST_RESULT_KEY, newValue: payload }))
      if (!result.has_update || !result.latest_version) return
      if (localStorage.getItem(UPDATE_NOTIFIED_VERSION_KEY) === result.latest_version) return
      localStorage.setItem(UPDATE_NOTIFIED_VERSION_KEY, result.latest_version)
      toast.info(`Mnemox v${result.latest_version} 已发布`, {
        description: '可以在「设置 · 系统」中查看更新说明并安装。',
        duration: 12000,
        actions: [{ label: '查看', variant: 'primary', onClick: () => useShell.getState().openSettings('system') }],
      })
      if (localStorage.getItem('sys_notif') !== 'false' && 'Notification' in window && Notification.permission === 'granted') {
        const n = new Notification('Mnemox 发现新版本', { body: `v${result.latest_version} 已发布，可在系统设置中更新。` })
        n.onclick = () => window.focus()
      }
    }
    const schedule = () => {
      if (destroyed || !enabled()) return
      timer = window.setTimeout(async () => {
        await run()
        schedule()
      }, intervalMs())
    }
    if (enabled()) {
      void run()
      schedule()
    }
    const onStorage = (e: StorageEvent) => {
      if (e.key !== UPDATE_AUTO_CHECK_KEY && e.key !== UPDATE_INTERVAL_MIN_KEY) return
      window.clearTimeout(timer)
      if (enabled()) {
        void run()
        schedule()
      }
    }
    window.addEventListener('storage', onStorage)
    return () => {
      destroyed = true
      window.clearTimeout(timer)
      window.removeEventListener('storage', onStorage)
    }
  }, [authenticated])
}
