import { apiFetch } from './apiClient'

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
  title?: string
  description?: string
  task_type?: string
  planned_date?: string
  estimated_minutes?: number
  route?: string
}

export interface AgentActionDraftResponse {
  action: AgentAction
  draft: AgentActionDraft
  requires_confirmation: boolean
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
