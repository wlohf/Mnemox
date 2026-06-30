import { apiFetch } from './apiClient'

export type CoachEventType =
  | 'chat.low_motivation_detected'
  | 'chat.frustration_detected'
  | 'chat.overload_detected'
  | 'pomodoro.interrupted'
  | 'pomodoro.distracted'
  | 'pomodoro.completed'
  | 'review.debt_high'
  | 'app.inactive_returned'
  | 'app.evaluate'

export type CoachNudgeStatus = 'pending' | 'shown' | 'accepted' | 'snoozed' | 'dismissed' | 'completed' | 'expired'
export type CoachChannel = 'chat_inline' | 'in_app_nudge' | 'agent_panel' | 'desktop_notification'

export type CoachFeedbackOutcome =
  | 'helpful'
  | 'accepted'
  | 'completed'
  | 'later'
  | 'snoozed'
  | 'dismissed'
  | 'too_disruptive'
  | 'too_hard'
  | 'too_easy'
  | 'irrelevant'
  | 'not_my_style'

export interface CoachEvent {
  id: string
  user_id: number
  event_type: string
  source: string
  severity: string
  payload: Record<string, any>
  dedupe_key?: string | null
  occurred_at?: string | null
  created_at?: string | null
}

export interface CoachNudge {
  id: string
  event_id?: string | null
  skill_id: string
  channel: CoachChannel
  priority: 'high' | 'medium' | 'low'
  title: string
  body: string
  suggested_action: {
    type?: string
    label?: string
    route?: string
    [key: string]: any
  }
  route?: string | null
  requires_confirmation: boolean
  draft?: Record<string, any> | null
  explainability?: {
    reason?: string
    signals?: string[]
    sources?: Array<{
      type?: string
      id?: number | string
      title?: string
      route?: string
      snippet?: string
      category?: string
    }>
    context_terms?: string[]
    policy?: {
      reason?: string
      evidence?: string[]
    }
  } | null
  status: CoachNudgeStatus
  expires_at?: string | null
  created_at?: string | null
  updated_at?: string | null
}

export interface CoachPolicyResult {
  should_intervene: boolean
  intervention_type?: string | null
  priority: 'high' | 'medium' | 'low'
  skill_id?: string | null
  channel?: string | null
  cooldown_until?: string | null
  reason: string
  evidence: string[]
  requires_confirmation: boolean
}

export interface CoachEvaluateResponse {
  nudge: CoachNudge | null
  policy: CoachPolicyResult
  event: CoachEvent | Record<string, any>
}

export interface CoachPreferences {
  enabled: boolean
  proactive_enabled: boolean
  desktop_notifications_enabled: boolean
  quiet_hours_start?: string | null
  quiet_hours_end?: string | null
  max_nudges_per_day: number
  min_minutes_between_nudges: number
  allowed_channels: string[]
  disabled_skill_ids: string[]
  updated_at?: string | null
}

export async function recordCoachEvent(body: {
  event_type: CoachEventType | string
  source?: string
  payload?: Record<string, any>
  severity?: string
  dedupe_key?: string
}): Promise<CoachEvent> {
  return await apiFetch<CoachEvent>('/api/coach/events', {
    method: 'POST',
    body: JSON.stringify({
      source: 'frontend',
      payload: {},
      severity: 'info',
      ...body,
    }),
  })
}

export async function evaluateCoach(body: {
  event_id?: string
  event?: {
    event_type: CoachEventType | string
    source?: string
    channel?: CoachChannel | string
    payload?: Record<string, any>
    severity?: string
    dedupe_key?: string
  }
  include_recent_notes?: boolean
  include_memories?: boolean
} = {}): Promise<CoachEvaluateResponse | null> {
  try {
    return await apiFetch<CoachEvaluateResponse>('/api/coach/evaluate', {
      method: 'POST',
      body: JSON.stringify(body),
    })
  } catch {
    return null
  }
}

export async function listCoachNudges(status?: CoachNudgeStatus, limit = 20): Promise<CoachNudge[] | null> {
  try {
    const qs = new URLSearchParams()
    if (status) qs.set('status', status)
    qs.set('limit', String(limit))
    return await apiFetch<CoachNudge[]>(`/api/coach/nudges?${qs.toString()}`)
  } catch {
    return null
  }
}

export async function markCoachNudgeShown(nudgeId: string): Promise<CoachNudge | null> {
  try {
    return await apiFetch<CoachNudge>(`/api/coach/nudges/${encodeURIComponent(nudgeId)}/shown`, {
      method: 'POST',
    })
  } catch {
    return null
  }
}

export async function recordCoachNudgeFeedback(
  nudgeId: string,
  body: { outcome: CoachFeedbackOutcome; notes?: string },
): Promise<{ ok: boolean; nudge_id: string; status: string } | null> {
  try {
    return await apiFetch<{ ok: boolean; nudge_id: string; status: string }>(`/api/coach/nudges/${encodeURIComponent(nudgeId)}/feedback`, {
      method: 'POST',
      body: JSON.stringify(body),
    })
  } catch {
    return null
  }
}

export async function getCoachSkills(): Promise<Array<Record<string, any>> | null> {
  try {
    return await apiFetch<Array<Record<string, any>>>('/api/coach/skills')
  } catch {
    return null
  }
}

export async function getCoachPreferences(): Promise<CoachPreferences | null> {
  try {
    return await apiFetch<CoachPreferences>('/api/coach/preferences')
  } catch {
    return null
  }
}

export async function updateCoachPreferences(patch: Partial<CoachPreferences>): Promise<CoachPreferences | null> {
  try {
    return await apiFetch<CoachPreferences>('/api/coach/preferences', {
      method: 'PATCH',
      body: JSON.stringify(patch),
    })
  } catch {
    return null
  }
}

export function detectCoachChatEvent(text: string): CoachEventType | null {
  const normalized = text.trim().toLowerCase()
  if (!normalized) return null
  if (/(自杀|不想活|伤害自己|结束生命|suicide|self-harm)/i.test(normalized)) {
    return 'chat.frustration_detected'
  }
  if (/(太多了|不知道先做什么|无从下手|来不及|任务太多|压得喘不过气|overwhelmed|too much|where to start)/i.test(normalized)) {
    return 'chat.overload_detected'
  }
  if (/(很差|我太差|废物|崩溃|烦死|气死|失败|做不到|讨厌学习|frustrated|angry|hopeless|i suck|i'm bad)/i.test(normalized)) {
    return 'chat.frustration_detected'
  }
  if (/(学不进去|不想学|没动力|坚持不下去|不想继续|太累了|cannot study|can't study|no motivation)/i.test(normalized)) {
    return 'chat.low_motivation_detected'
  }
  return null
}
