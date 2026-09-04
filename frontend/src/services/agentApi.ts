import { apiFetch } from './apiClient'
import type { CoachPreferences } from './coachApi'

export type AgentNegativeReasonCode =
  | 'too_long'
  | 'too_late'
  | 'too_easy'
  | 'too_hard'
  | 'too_disruptive'
  | 'irrelevant_to_goal'
  | 'already_known'
  | 'other'

export interface AgentProfileControlLog {
  id: string
  agent?: string
  status?: string
  operation?: string
  operation_label?: string
  item_id?: string
  item_text?: string | null
  message?: string
  created_at?: string
}

export interface AgentAction {
  id: string
  title: string
  reason: string
  action_type: string
  priority: 'high' | 'medium' | 'low'
  estimated_minutes: number
  route: string
  target?: unknown
  source?: string
  explainability?: {
    data_signals?: string[]
    feedback_refs?: string[]
    recommendation_reason?: string
    summary?: string
    adjustment?: string
    reason_adjustments?: string[]
    audit?: {
      action_type?: string
      topic?: string
      source?: string
      write_requires_confirmation?: boolean
    }
  }
}

export interface AgentPlannerInfo {
  source: 'rules' | 'llm'
  strategy?: string | null
  fallback_plan?: string | null
}

export interface AgentActionDraft {
  operation: 'create_task' | 'navigate'
  goal_id?: number | null
  goal_title?: string
  title?: string
  description?: string
  task_type?: string
  planned_date?: string
  estimated_minutes?: number
  route?: string
  source_job_id?: string
  source_action_id?: string
}

export interface AgentActionDraftResponse {
  action: AgentAction
  draft: AgentActionDraft
  requires_confirmation: boolean
}

export interface AgentGoalContextItem {
  id?: number | string
  title?: string
  route?: string
  [key: string]: unknown
}

export interface AgentGoalContext {
  date: string
  generated_at: string
  active_goal: null | {
    id: number
    title: string
    description?: string | null
    deadline?: string | null
    target_level?: string | null
    material_id?: number | null
    route?: string
    progress?: {
      pending_task_count?: number
      completed_today_count?: number
      overdue_task_count?: number
      today_task_count?: number
    }
  }
  goal_creation?: {
    title: string
    message: string
    route: string
    requires_confirmation: boolean
  }
  today_focus: {
    id: string
    action_id: string
    title: string
    reason: string
    estimated_minutes: number
    route: string
    target?: unknown
    requires_confirmation?: boolean
  }
  supporting_context: {
    notes?: AgentGoalContextItem[]
    materials?: AgentGoalContextItem[]
    wrong_questions?: AgentGoalContextItem[]
    review_items?: AgentGoalContextItem[]
  }
  risk_flags: {
    no_daily_plan?: boolean
    review_debt_high?: boolean
    goal_stale?: boolean
  }
  evidence?: string[]
  core_profile?: AgentCoreProfile | null
}

export interface AgentActionExecuteResponse {
  status: string
  action: AgentAction
  draft: AgentActionDraft
  created_task?: Record<string, unknown> | null
  route?: string | null
}

export type AgentWriteIntent = 'none' | 'create_note' | 'create_goal_tasks' | 'add_daily_plan_items'

export interface AgentWriteDraftResponse {
  intent: AgentWriteIntent
  confidence?: number
  summary?: string
  draft: Record<string, any>
  duplicate_warnings?: string[]
  requires_confirmation?: boolean
}

export interface AgentWriteExecuteResponse {
  status: string
  intent: AgentWriteIntent
  created?: Record<string, any> | null
  route?: string | null
  message?: string
}

export interface AgentPersonalizationItem {
  id: string
  text: string
  source?: string
  confidence?: number
  locked?: boolean
  ignored?: boolean
  inaccurate?: boolean
}

export interface AgentPersonalization {
  summary?: string[]
  summary_items?: AgentPersonalizationItem[]
  learned_preferences?: string[]
  preference_items?: AgentPersonalizationItem[]
  feedback_stats?: {
    accepted?: number
    rejected_or_delayed?: number
    accepted_rate?: number | null
    outcome_counts?: Record<string, number>
    by_action_type?: Record<string, { positive?: number; negative?: number }>
    by_topic?: Record<string, { positive?: number; negative?: number }>
    by_reason_code?: Record<string, number>
  }
  feedback_impacts?: Array<{ dimension?: string; key?: string; effect?: string; message?: string }>
  profile_control_logs?: AgentProfileControlLog[]
  recent_feedback?: Array<{
    action_id?: string
    action_type?: string
    knowledge_point?: string
    topic?: string
    source_signal?: string
    reason_code?: AgentNegativeReasonCode
    reason_label?: string
    outcome?: string
    outcome_label?: string
    notes?: string
    reason?: string
    effectiveness?: number | null
    recorded_at?: string
  }>
  avoid_action_ids?: string[]
  avoid_action_types?: string[]
  avoid_topics?: string[]
  controls?: {
    ignored_items?: string[]
    inaccurate_items?: string[]
    locked_items?: string[]
  }
  material_sources?: Array<{ file_type: string; count: number }>
  updated_at?: string
}

export interface AgentBrief {
  date: string
  generated_at: string
  autonomy_level: string
  readiness_score: number
  risk_level: 'low' | 'medium' | 'high'
  state_summary: string
  current_focus: string
  next_actions: AgentAction[]
  watch_signals: string[]
  planner?: AgentPlannerInfo | null
  context: {
    profile?: Record<string, unknown>
    tasks?: Record<string, unknown>
    review?: Record<string, unknown>
    learning?: Record<string, unknown>
    weaknesses?: Record<string, unknown>
    memory?: Record<string, unknown>
    personalization?: AgentPersonalization
  }
}

export interface AgentRuntimeInfo {
  status: 'idle' | 'running'
  agents: Array<{ name: string; display_name: string; description: string }>
  task_queue: Array<Record<string, unknown>>
  execution_logs: Array<Record<string, unknown>>
  profile_control_logs?: AgentProfileControlLog[]
  kernel_daily_budget?: AgentKernelDailyBudget
}

export interface AgentKernelDailyBudget {
  date: string
  timezone: 'UTC'
  model_calls: number
  estimated_tokens: number
  actual_usage_calls?: number
  actual_tokens?: number
  configured_cost_usd?: number
  model_call_limit: number
  estimated_token_limit: number
  remaining_model_calls: number
  remaining_estimated_tokens: number
}

export interface AgentKernelUsage {
  model_calls: number
  estimated_input_tokens: number
  estimated_output_tokens: number
  estimated_total_tokens: number
  actual_input_tokens?: number
  actual_output_tokens?: number
  actual_total_tokens?: number
  actual_usage_calls?: number
  unreconciled_calls?: number
  configured_cost_usd?: number
  provider?: string | null
  model?: string | null
  usage_source?: 'provider' | 'mixed' | 'estimated_only'
  run_model_calls?: number
  run_estimated_input_tokens?: number
  run_estimated_output_tokens?: number
  run_estimated_total_tokens?: number
  run_actual_input_tokens?: number
  run_actual_output_tokens?: number
  run_actual_total_tokens?: number
  run_actual_usage_calls?: number
  run_unreconciled_calls?: number
  run_configured_cost_usd?: number
  model_call_limit: number
  estimated_token_limit: number
  budget_reason?:
    | 'model_call_limit'
    | 'estimated_token_limit'
    | 'daily_model_call_limit'
    | 'daily_estimated_token_limit'
  daily_budget?: AgentKernelDailyBudget
}

export interface AgentKernelRunResponse {
  status: 'completed' | 'failed' | 'fallback' | 'cancelled' | 'unavailable'
  reason?: string
  strategy?: string | null
  fallback_plan?: string | null
  next_actions: Array<Record<string, unknown>>
  steps: Array<Record<string, unknown>>
  error?: string | null
  usage?: AgentKernelUsage
  fallback?: {
    source?: 'rules'
    reason?: string
    available?: boolean
    generated_at?: string | null
    risk_level?: string | null
  } | null
  job_id: string
}

export interface AgentKernelPreparedJobResponse {
  job: Record<string, unknown>
}

export interface AgentKernelActionDraftResponse extends AgentActionDraftResponse {
  draft_id: string
  job_id: string
  status: 'prepared' | 'executing' | 'completed'
  execution_result?: AgentKernelActionExecuteResponse | null
  idempotent?: boolean
}

export interface AgentKernelActionExecuteResponse extends AgentActionExecuteResponse {
  job_id: string
  draft_id: string
  idempotent: boolean
}

export interface AgentJobStreamHandlers {
  onSnapshot?: (job: Record<string, unknown>) => void
  onLog?: (log: Record<string, unknown>) => void
  onTerminal?: (job: Record<string, unknown>) => void
  onTimeout?: (jobId: string) => void
  onError?: (code: string) => void
}

export type AgentJobStreamOutcome = 'terminal' | 'timeout' | 'ended' | 'aborted' | 'error'

export interface AgentProactiveRuntimeStatus {
  preference: CoachPreferences
  scheduler: {
    available: boolean
    running: boolean
    poll_interval_seconds?: number | null
    user_interval_seconds?: number | null
    retry_interval_seconds?: number | null
    user_timeout_seconds?: number | null
    quiet_hours_deferred?: number | null
    timed_out_users?: number | null
    last_run_at?: string | null
    last_success_at?: string | null
    last_error_at?: string | null
    message: string
  }
}

export interface WeeklyLearningReportStep {
  title: string
  reason: string
  route: string
  estimated_minutes: number
}

export interface WeeklyConsolidationSource {
  kind: 'note' | 'review' | 'wrong_question'
  id: number
  title: string
  excerpt: string
  route: string
  observed_at: string | null
  ownership: 'mnemox' | 'obsidian_read_only' | 'obsidian_conflict'
  source_ref: string
}

export interface WeeklyKnowledgeConsolidation {
  version: number
  draft_key: string
  content_hash: string
  week_start: string
  week_end_exclusive: string
  scan_start_utc: string
  scan_end_utc: string
  scan_end_inclusive: boolean
  source_counts: {
    notes: number
    reviews: number
    wrong_questions: number
    total: number
  }
  source_limit_per_kind: number
  truncated: Record<'notes' | 'reviews' | 'wrong_questions', boolean>
  sources: WeeklyConsolidationSource[]
  markdown: string
  write_policy: {
    mode: 'copy_only'
    automatic_write: false
    obsidian_write_allowed: false
    imported_source_count: number
    rollback: string
  }
}

export interface WeeklyLearningReport {
  generated_at: string
  time_zone: string
  headline: string
  wins: string[]
  attention: string[]
  next_steps: WeeklyLearningReportStep[]
  metrics: Record<string, unknown>
  coverage: Record<string, unknown>
  consolidation: WeeklyKnowledgeConsolidation
  disclaimer: string
}

export interface AgentTriggerResponse {
  job: Record<string, unknown>
  result: {
    agent: string
    task: string
    status: string
    summary: string
    actions: Array<Record<string, unknown>>
    data: Record<string, unknown>
  }
  runtime: AgentRuntimeInfo
}

export async function getAgentBrief(useLlm = false): Promise<AgentBrief> {
  return await apiFetch<AgentBrief>(`/api/agent/brief${useLlm ? '?use_llm=true' : ''}`)
}

export interface AgentMemoryCandidate {
  id: number
  memory_key: string
  memory_value: string
  category: string
  confidence: number
  status?: string
  review_status?: 'staged' | 'confirmed' | 'ignored' | 'inaccurate' | string | null
  memory_type?: string | null
  source_type?: string | null
  source_id?: string | number | null
  evidence?: string[] | string | null
  expires_at?: string | null
  material_id?: number | null
  is_locked?: number | boolean
  created_at?: string | null
  updated_at?: string | null
}

export interface AgentCoreProfile {
  id?: number | null
  memory_key?: string
  memory_value: string
  category?: string
  confidence?: number
  updated_at?: string | null
  evidence?: string[] | string | null
  signals?: Array<{ label?: string; value?: string; confidence?: number }>
}

export interface AgentCoreProfileResponse {
  memory?: AgentMemoryCandidate | null
  profile?: Record<string, unknown> | null
}

export interface AgentMemoryLearningRun {
  ok?: boolean
  checkpoint_at?: string
  scanned_events?: number
  created?: number
  staged?: number
  confirmed?: number
  core_profile?: AgentCoreProfile | null
  message?: string
}

export async function getAgentGoalContext(goalId?: number): Promise<AgentGoalContext> {
  const suffix = goalId ? `?goal_id=${encodeURIComponent(String(goalId))}` : ''
  return await apiFetch<AgentGoalContext>(`/api/agent/goal-context${suffix}`)
}

export async function listAgentMemoryCandidates(): Promise<AgentMemoryCandidate[]> {
  try {
    return await apiFetch<AgentMemoryCandidate[]>('/api/agent/memory/candidates')
  } catch {
    return []
  }
}

export async function confirmAgentMemoryCandidate(
  id: number,
  options: { lock?: boolean } = {},
): Promise<AgentMemoryCandidate | { ok: boolean } | null> {
  try {
    return await apiFetch<AgentMemoryCandidate | { ok: boolean }>(`/api/agent/memory/candidates/${id}/confirm`, {
      method: 'POST',
      body: JSON.stringify(options),
    })
  } catch {
    return null
  }
}

export async function ignoreAgentMemoryCandidate(
  id: number,
  options: { reason?: 'ignored' | 'inaccurate' | string } = {},
): Promise<AgentMemoryCandidate | { ok: boolean } | null> {
  try {
    return await apiFetch<AgentMemoryCandidate | { ok: boolean }>(`/api/agent/memory/candidates/${id}/ignore`, {
      method: 'POST',
      body: JSON.stringify(options),
    })
  } catch {
    return null
  }
}

export async function runAgentMemoryLearning(): Promise<AgentMemoryLearningRun | null> {
  try {
    return await apiFetch<AgentMemoryLearningRun>('/api/agent/memory/run-learning', {
      method: 'POST',
      body: JSON.stringify({}),
    })
  } catch {
    return null
  }
}

export async function getAgentCoreProfile(): Promise<AgentCoreProfile | null> {
  try {
    const data = await apiFetch<AgentCoreProfile | AgentCoreProfileResponse>('/api/agent/memory/core-profile')
    if ('memory_value' in data) return data
    const profile = (data as AgentCoreProfileResponse).profile || {}
    const memory = (data as AgentCoreProfileResponse).memory || null
    return {
      id: memory?.id ?? null,
      memory_key: memory?.memory_key || 'agent_core_profile',
      memory_value: JSON.stringify(profile),
      category: memory?.category || 'system',
      confidence: memory?.confidence,
      updated_at: memory?.updated_at || (typeof profile.updated_at === 'string' ? profile.updated_at : null),
      evidence: memory?.evidence,
    }
  } catch {
    return null
  }
}

export async function getAgentPrompt(): Promise<{ prompt: string }> {
  return await apiFetch<{ prompt: string }>('/api/agent/prompt')
}


export async function draftAgentWrite(message: string): Promise<AgentWriteDraftResponse> {
  return await apiFetch<AgentWriteDraftResponse>('/api/agent/write/draft', {
    method: 'POST',
    body: JSON.stringify({ message }),
  })
}

export async function executeAgentWrite(intent: AgentWriteIntent, draft: Record<string, any>): Promise<AgentWriteExecuteResponse> {
  return await apiFetch<AgentWriteExecuteResponse>('/api/agent/write/execute', {
    method: 'POST',
    body: JSON.stringify({ intent, draft }),
  })
}

export async function getAgentActionDraft(actionId: string, useLlm = false): Promise<AgentActionDraftResponse | null> {
  try {
    const suffix = useLlm ? '?use_llm=true' : ''
    return await apiFetch<AgentActionDraftResponse>(`/api/agent/actions/${encodeURIComponent(actionId)}/draft${suffix}`)
  } catch {
    return null
  }
}

export async function getAgentGoalContextActionDraft(actionId: string): Promise<AgentActionDraftResponse | null> {
  try {
    return await apiFetch<AgentActionDraftResponse>(`/api/agent/goal-context/actions/${encodeURIComponent(actionId)}/draft`, {
      method: 'POST',
      body: JSON.stringify({}),
    })
  } catch {
    return null
  }
}

export async function executeAgentAction(actionId: string, useLlm = false): Promise<AgentActionExecuteResponse | null> {
  try {
    const suffix = useLlm ? '?use_llm=true' : ''
    return await apiFetch<AgentActionExecuteResponse>(`/api/agent/actions/${encodeURIComponent(actionId)}/execute${suffix}`, {
      method: 'POST',
    })
  } catch {
    return null
  }
}

export async function getAgentStatus(): Promise<AgentRuntimeInfo | null> {
  try {
    return await apiFetch<AgentRuntimeInfo>('/api/agent/status')
  } catch {
    return null
  }
}

export async function prepareAgentKernel(resumeFromJobId?: string): Promise<AgentKernelPreparedJobResponse | null> {
  try {
    return await apiFetch<AgentKernelPreparedJobResponse>('/api/agent/kernel/jobs', {
      method: 'POST',
      body: JSON.stringify({
        resume_from_job_id: resumeFromJobId || null,
        max_steps: 6,
      }),
    })
  } catch {
    return null
  }
}

export async function runPreparedAgentKernel(preparedJobId: string): Promise<AgentKernelRunResponse | null> {
  try {
    return await apiFetch<AgentKernelRunResponse>('/api/agent/kernel/run', {
      method: 'POST',
      body: JSON.stringify({ prepared_job_id: preparedJobId }),
    })
  } catch {
    return null
  }
}

export async function cancelAgentJob(jobId: string): Promise<{ job: Record<string, unknown>; changed: boolean } | null> {
  try {
    return await apiFetch<{ job: Record<string, unknown>; changed: boolean }>(
      `/api/agent/jobs/${encodeURIComponent(jobId)}/cancel`,
      { method: 'POST' },
    )
  } catch {
    return null
  }
}

export async function prepareAgentKernelAction(
  jobId: string,
  actionId: string,
): Promise<AgentKernelActionDraftResponse | null> {
  try {
    return await apiFetch<AgentKernelActionDraftResponse>(
      `/api/agent/jobs/${encodeURIComponent(jobId)}/actions/${encodeURIComponent(actionId)}/draft`,
      { method: 'POST' },
    )
  } catch {
    return null
  }
}

export async function confirmAgentKernelAction(
  jobId: string,
  actionId: string,
  draftId: string,
): Promise<AgentKernelActionExecuteResponse | null> {
  try {
    return await apiFetch<AgentKernelActionExecuteResponse>(
      `/api/agent/jobs/${encodeURIComponent(jobId)}/actions/${encodeURIComponent(actionId)}/confirm`,
      { method: 'POST', body: JSON.stringify({ draft_id: draftId }) },
    )
  } catch {
    return null
  }
}

export async function streamAgentJobEvents(
  jobId: string,
  handlers: AgentJobStreamHandlers = {},
  signal?: AbortSignal,
): Promise<AgentJobStreamOutcome> {
  try {
    const response = await fetch(`/api/agent/jobs/${encodeURIComponent(jobId)}/events`, {
      method: 'GET',
      credentials: 'same-origin',
      headers: { Accept: 'text/event-stream' },
      signal,
    })
    if (!response.ok || !response.body) {
      handlers.onError?.(`http_${response.status}`)
      return 'error'
    }

    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''

    const dispatchBlock = (block: string): AgentJobStreamOutcome | null => {
      const data = block
        .split(/\r?\n/)
        .filter((line) => line.startsWith('data:'))
        .map((line) => line.slice(5).trimStart())
        .join('\n')
      if (!data) return null
      try {
        const payload = JSON.parse(data) as Record<string, any>
        if (payload.type === 'snapshot' && payload.job) handlers.onSnapshot?.(payload.job)
        if (payload.type === 'log' && payload.log) handlers.onLog?.(payload.log)
        if (payload.type === 'terminal' && payload.job) {
          handlers.onTerminal?.(payload.job)
          return 'terminal'
        }
        if (payload.type === 'timeout') {
          handlers.onTimeout?.(String(payload.job_id || jobId))
          return 'timeout'
        }
        if (payload.type === 'error') {
          handlers.onError?.(String(payload.code || 'stream_error'))
          return 'error'
        }
      } catch {
        handlers.onError?.('invalid_stream_event')
        return 'error'
      }
      return null
    }

    while (true) {
      const { done, value } = await reader.read()
      buffer += decoder.decode(value || new Uint8Array(), { stream: !done })
      const blocks = buffer.split(/\r?\n\r?\n/)
      buffer = blocks.pop() || ''
      for (const block of blocks) {
        const outcome = dispatchBlock(block)
        if (outcome) {
          await reader.cancel().catch(() => undefined)
          return outcome
        }
      }
      if (done) {
        const outcome = buffer ? dispatchBlock(buffer) : null
        return outcome || 'ended'
      }
    }
  } catch (error) {
    if (error instanceof Error && error.name === 'AbortError') return 'aborted'
    handlers.onError?.('stream_unavailable')
    return 'error'
  }
}

export async function getAgentProactiveRuntimeStatus(): Promise<AgentProactiveRuntimeStatus | null> {
  try {
    return await apiFetch<AgentProactiveRuntimeStatus>('/api/agent/runtime/proactive-status')
  } catch {
    return null
  }
}

export async function getWeeklyLearningReport(timeZone = 'UTC'): Promise<WeeklyLearningReport | null> {
  try {
    const query = new URLSearchParams({ time_zone: timeZone })
    return await apiFetch<WeeklyLearningReport>(`/api/agent/weekly-report?${query.toString()}`)
  } catch {
    return null
  }
}

export async function triggerAgentTask(
  agent: 'study_plan' | 'review' | 'chat',
  task = 'run',
  payload: Record<string, unknown> = {},
): Promise<AgentTriggerResponse | null> {
  try {
    return await apiFetch<AgentTriggerResponse>('/api/agent/tasks/trigger', {
      method: 'POST',
      body: JSON.stringify({ agent, task, payload }),
    })
  } catch {
    return null
  }
}

export async function recordAgentActionFeedback(
  actionId: string,
  body: { outcome: 'accepted' | 'dismissed' | 'completed' | 'failed' | 'adjusted' | 'later' | 'useless' | 'helpful' | 'rejected' | 'snoozed'; notes?: string; effectiveness?: number; reason_code?: AgentNegativeReasonCode },
): Promise<{ ok: boolean } | null> {
  try {
    return await apiFetch<{ ok: boolean }>(`/api/agent/actions/${encodeURIComponent(actionId)}/feedback`, {
      method: 'POST',
      body: JSON.stringify(body),
    })
  } catch {
    return null
  }
}


export async function controlAgentProfileItem(
  itemId: string,
  operation: 'ignore' | 'inaccurate' | 'lock' | 'unlock' | 'restore',
): Promise<{ ok: boolean; item_id: string; operation: string } | null> {
  try {
    return await apiFetch<{ ok: boolean; item_id: string; operation: string }>(`/api/agent/profile/items/${encodeURIComponent(itemId)}`, {
      method: 'PATCH',
      body: JSON.stringify({ operation }),
    })
  } catch {
    return null
  }
}
