import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Alert, Button, Card, Col, Collapse, Dropdown, Empty, Input, List, Modal, Popconfirm, Progress, Row, Space, Switch, Tag, Typography, message } from 'antd'
import { BulbOutlined, CheckCircleOutlined, CloseCircleOutlined, ExperimentOutlined, LockOutlined, ReloadOutlined, ThunderboltOutlined, UserOutlined } from '@ant-design/icons'
import { PageShell } from '../components/PageShell'
import { CoachNudgesPanel } from '../components/agent/CoachNudgesPanel'
import { NorthStarMetricsCard } from '../components/agent/NorthStarMetricsCard'
import { ProactiveReviewChecksCard } from '../components/agent/ProactiveReviewChecksCard'
import { WeeklyLearningReportCard } from '../components/agent/WeeklyLearningReportCard'
import {
  controlAgentProfileItem,
  cancelAgentJob,
  confirmAgentKernelAction,
  executeAgentAction,
  getAgentActionDraft,
  getAgentBrief,
  getAgentCoreProfile,
  getAgentGoalContext,
  getAgentGoalContextActionDraft,
  getAgentProactiveRuntimeStatus,
  getAgentStatus,
  getWeeklyLearningReport,
  ignoreAgentMemoryCandidate,
  listAgentMemoryCandidates,
  prepareAgentKernel,
  prepareAgentKernelAction,
  recordAgentActionFeedback,
  runAgentMemoryLearning,
  runPreparedAgentKernel,
  streamAgentJobEvents,
  triggerAgentTask,
  confirmAgentMemoryCandidate,
  type AgentAction,
  type AgentActionDraftResponse,
  type AgentBrief,
  type AgentCoreProfile,
  type AgentGoalContext,
  type AgentGoalContextItem,
  type AgentKernelActionDraftResponse,
  type AgentMemoryCandidate,
  type AgentNegativeReasonCode,
  type AgentPersonalizationItem,
  type AgentProactiveRuntimeStatus,
  type AgentRuntimeInfo,
  type WeeklyLearningReport,
} from '../services/agentApi'
import {
  listCoachNudges,
  getCoachNudgeReplay,
  markCoachNudgeShown,
  markPendingCoachNudgesShown,
  recordCoachNudgeFeedback,
  startCoachNudgeAction,
  updateCoachPreferences,
  type CoachActionAttempt,
  type CoachNudgeReplay,
  type CoachFeedbackOutcome,
  type CoachNudge,
} from '../services/coachApi'
import {
  findConceptAssociations,
  type AssociationRecallResponse,
  type ConceptAssociation,
} from '../services/associationApi'
import {
  getCoachExperimentReport,
  getNorthStarMetrics,
  type CoachExperimentReport,
  type NorthStarMetricsReport,
} from '../services/analyticsApi'

const { Paragraph, Text } = Typography

const negativeReasonOptions: Array<{ key: AgentNegativeReasonCode; label: string }> = [
  { key: 'too_long', label: '太长' },
  { key: 'too_late', label: '太晚' },
  { key: 'too_easy', label: '太简单' },
  { key: 'too_hard', label: '太难' },
  { key: 'too_disruptive', label: '太打扰' },
  { key: 'irrelevant_to_goal', label: '和当前目标无关' },
  { key: 'already_known', label: '已经掌握' },
  { key: 'other', label: '其他原因' },
]

const profileOperationCopy = {
  ignore: { label: '不再使用这条', title: '之后不再让这条画像影响建议？' },
  inaccurate: { label: '这不准确', title: '把这条画像标记为不准确？' },
  lock: { label: '锁定', title: '锁定这条画像理解？' },
  unlock: { label: '取消锁定', title: '取消锁定后允许 Agent 继续更新这条理解？' },
  restore: { label: '恢复', title: '恢复这条画像理解？' },
}

function priorityColor(priority: AgentAction['priority']) {
  if (priority === 'high') return 'red'
  if (priority === 'medium') return 'orange'
  return 'green'
}

function riskColor(risk?: AgentBrief['risk_level']) {
  if (risk === 'high') return 'red'
  if (risk === 'medium') return 'orange'
  return 'green'
}

function activeKernelJobIdFromRuntime(runtime: AgentRuntimeInfo | null): string | null {
  const active = (runtime?.task_queue || []).find(
    (job) => job.agent === 'kernel' && ['pending', 'running', 'cancelling'].includes(String(job.status || '')),
  )
  return active?.id ? String(active.id) : null
}

function kernelActionsFromJob(job: Record<string, unknown>): AgentAction[] {
  const result = job.result && typeof job.result === 'object'
    ? job.result as Record<string, unknown>
    : {}
  const actions = Array.isArray(result.next_actions) ? result.next_actions : []
  return actions.filter((item): item is AgentAction => Boolean(
    item
    && typeof item === 'object'
    && typeof (item as Record<string, unknown>).id === 'string'
    && typeof (item as Record<string, unknown>).title === 'string',
  ))
}

function kernelUsesRulesFallback(job: Record<string, unknown>): boolean {
  const result = job.result && typeof job.result === 'object'
    ? job.result as Record<string, unknown>
    : {}
  const fallback = result.fallback && typeof result.fallback === 'object'
    ? result.fallback as Record<string, unknown>
    : {}
  return result.status === 'fallback' && fallback.source === 'rules'
}

function kernelActionExecution(
  job: Record<string, unknown>,
  actionId: string,
): Record<string, unknown> | null {
  const result = job.result && typeof job.result === 'object'
    ? job.result as Record<string, unknown>
    : {}
  const executions = result.action_executions && typeof result.action_executions === 'object'
    ? result.action_executions as Record<string, unknown>
    : {}
  const execution = executions[actionId]
  return execution && typeof execution === 'object' ? execution as Record<string, unknown> : null
}

function routeWithCoachAttempt(route: string, attempt: CoachActionAttempt, nudgeId: string) {
  const url = new URL(route, window.location.origin)
  url.searchParams.set('coach_attempt', attempt.id)
  url.searchParams.set('coach_nudge', nudgeId)
  const minutes = Number(attempt.action_payload?.minutes)
  if (Number.isFinite(minutes) && minutes > 0) {
    url.searchParams.set('coach_minutes', String(minutes))
  }
  return `${url.pathname}${url.search}${url.hash}`
}

function autonomyLabel(level?: string) {
  if (level === 'copilot+') return 'Copilot+｜深度协同'
  if (level === 'copilot') return 'Copilot｜主动协同'
  if (level === 'coach') return 'Coach｜教练引导'
  return 'Observe｜观察学习'
}

function formatCompactValue(value: unknown): string {
  if (value === null || value === undefined) return ''
  if (Array.isArray(value)) return value.map(formatCompactValue).filter(Boolean).join('；')
  if (typeof value === 'object') {
    const entries = Object.entries(value as Record<string, unknown>)
      .map(([key, item]) => `${key}: ${formatCompactValue(item)}`)
      .filter((item) => !item.endsWith(': '))
    return entries.join('，')
  }
  return String(value)
}

function parseEvidence(evidence: AgentMemoryCandidate['evidence'] | AgentCoreProfile['evidence']): string[] {
  if (!evidence) return []
  if (Array.isArray(evidence)) return evidence.map(formatCompactValue).filter(Boolean)
  if (typeof evidence !== 'string') return [formatCompactValue(evidence)].filter(Boolean)
  const trimmed = evidence.trim()
  if (!trimmed) return []
  try {
    const parsed = JSON.parse(trimmed)
    if (Array.isArray(parsed)) return parsed.map(formatCompactValue).filter(Boolean)
    if (parsed && typeof parsed === 'object') {
      return Object.entries(parsed).map(([key, value]) => `${key}: ${formatCompactValue(value)}`).filter(Boolean)
    }
  } catch {
    // Evidence may already be a plain human-readable sentence.
  }
  return [trimmed]
}

function confidenceLabel(value?: number | null) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return '-'
  return `${Math.round(Number(value) * 100)}%`
}

function coreProfileLines(profile: AgentCoreProfile | null): string[] {
  if (!profile?.memory_value) return []
  const raw = profile.memory_value.trim()
  if (!raw) return []
  try {
    const parsed = JSON.parse(raw)
    if (Array.isArray(parsed)) return parsed.map((item) => String(item)).filter(Boolean)
    if (parsed && typeof parsed === 'object') {
      const summary = (parsed as { summary?: unknown }).summary
      if (Array.isArray(summary)) {
        const summaryLines = summary.flatMap((group) => {
          if (!group || typeof group !== 'object') return [formatCompactValue(group)]
          const category = String((group as { category?: unknown }).category || 'profile')
          const items = (group as { items?: unknown }).items
          if (Array.isArray(items)) return items.slice(0, 4).map((item) => `${category}: ${formatCompactValue(item)}`)
          return [`${category}: ${formatCompactValue(group)}`]
        }).filter(Boolean)
        if (summaryLines.length > 0) return summaryLines
      }
      return Object.entries(parsed)
        .filter(([key]) => key !== 'summary')
        .map(([key, value]) => `${key}: ${formatCompactValue(value)}`)
        .filter(Boolean)
    }
  } catch {
    // Core profile may be a curated plain-text summary.
  }
  return raw.split('\n').map((line) => line.trim()).filter(Boolean)
}

export function AgentPage() {
  const navigate = useNavigate()
  const [loading, setLoading] = useState(false)
  const [brief, setBrief] = useState<AgentBrief | null>(null)
  const [useLlm, setUseLlm] = useState(false)
  const [draftLoading, setDraftLoading] = useState(false)
  const [draft, setDraft] = useState<AgentActionDraftResponse | null>(null)
  const [executeLoading, setExecuteLoading] = useState(false)
  const [runtime, setRuntime] = useState<AgentRuntimeInfo | null>(null)
  const [kernelLoading, setKernelLoading] = useState<string | null>(null)
  const [activeKernelJobId, setActiveKernelJobId] = useState<string | null>(null)
  const [kernelTraceJobId, setKernelTraceJobId] = useState<string | null>(null)
  const [kernelTrace, setKernelTrace] = useState<Array<Record<string, unknown>>>([])
  const [kernelActionDraft, setKernelActionDraft] = useState<AgentKernelActionDraftResponse | null>(null)
  const [kernelActionLoading, setKernelActionLoading] = useState<string | null>(null)
  const kernelStreamAbortRef = useRef<AbortController | null>(null)
  const [proactiveRuntime, setProactiveRuntime] = useState<AgentProactiveRuntimeStatus | null>(null)
  const [proactiveSaving, setProactiveSaving] = useState(false)
  const [weeklyReport, setWeeklyReport] = useState<WeeklyLearningReport | null>(null)
  const [weeklyReportLoading, setWeeklyReportLoading] = useState(false)
  const [northStarMetrics, setNorthStarMetrics] = useState<NorthStarMetricsReport | null>(null)
  const [coachExperiment, setCoachExperiment] = useState<CoachExperimentReport | null>(null)
  const [goalContext, setGoalContext] = useState<AgentGoalContext | null>(null)
  const [coachNudges, setCoachNudges] = useState<CoachNudge[]>([])
  const [coachReplay, setCoachReplay] = useState<CoachNudgeReplay | null>(null)
  const [coachReplayLoading, setCoachReplayLoading] = useState(false)
  const markedCoachNudgeIds = useRef(new Set<string>())
  const [associationText, setAssociationText] = useState('')
  const [associationLoading, setAssociationLoading] = useState(false)
  const [associationResult, setAssociationResult] = useState<AssociationRecallResponse | null>(null)
  const [expandedAssociationIds, setExpandedAssociationIds] = useState<Set<number>>(new Set())
  const associationShownNudgeIds = useRef(new Set<string>())
  const associationFeedbackIds = useRef(new Set<string>())
  const [agentLoading, setAgentLoading] = useState<string | null>(null)
  const [showDebug, setShowDebug] = useState(false)
  const [memoryCandidates, setMemoryCandidates] = useState<AgentMemoryCandidate[]>([])
  const [coreProfile, setCoreProfile] = useState<AgentCoreProfile | null>(null)
  const [memoryReviewLoading, setMemoryReviewLoading] = useState(false)
  const [memoryActionLoading, setMemoryActionLoading] = useState<number | 'run' | null>(null)

  const loadRuntime = async () => {
    const data = await getAgentStatus()
    if (data) {
      setRuntime(data)
      setActiveKernelJobId(activeKernelJobIdFromRuntime(data))
    }
  }

  const loadProactiveRuntime = async () => {
    const data = await getAgentProactiveRuntimeStatus()
    if (data) setProactiveRuntime(data)
  }

  const loadWeeklyReport = async () => {
    setWeeklyReportLoading(true)
    const timeZone = Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC'
    const report = await getWeeklyLearningReport(timeZone)
    setWeeklyReportLoading(false)
    if (!report) {
      message.error('本周复盘暂时无法生成，请稍后重试')
      return
    }
    setWeeklyReport(report)
  }

  const loadNorthStarMetrics = async () => {
    const timeZone = Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC'
    const [report, experiment] = await Promise.all([
      getNorthStarMetrics(28, timeZone),
      getCoachExperimentReport(28),
    ])
    setNorthStarMetrics(report)
    setCoachExperiment(experiment)
  }

  const loadCoachNudges = async () => {
    const data = await listCoachNudges(undefined, 8)
    if (data) setCoachNudges(data)
  }

  const loadAgentMemoryReview = async () => {
    setMemoryReviewLoading(true)
    const [candidates, profile] = await Promise.all([
      listAgentMemoryCandidates(),
      getAgentCoreProfile(),
    ])
    setMemoryCandidates(candidates || [])
    setCoreProfile(profile)
    setMemoryReviewLoading(false)
  }

  const load = async (llm = useLlm) => {
    setLoading(true)
    const [data, runtimeData, proactiveRuntimeData, nudgesData, goalData, candidatesData, profileData, metricsData, experimentData] = await Promise.all([
      getAgentBrief(llm),
      getAgentStatus(),
      getAgentProactiveRuntimeStatus(),
      listCoachNudges(undefined, 8),
      getAgentGoalContext().catch(() => null),
      listAgentMemoryCandidates(),
      getAgentCoreProfile(),
      getNorthStarMetrics(28, Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC'),
      getCoachExperimentReport(28),
    ])
    setLoading(false)
    if (runtimeData) {
      setRuntime(runtimeData)
      setActiveKernelJobId(activeKernelJobIdFromRuntime(runtimeData))
    }
    if (proactiveRuntimeData) setProactiveRuntime(proactiveRuntimeData)
    if (nudgesData) setCoachNudges(nudgesData)
    if (goalData) setGoalContext(goalData)
    setMemoryCandidates(candidatesData || [])
    setCoreProfile(profileData)
    setNorthStarMetrics(metricsData)
    setCoachExperiment(experimentData)
    if (!data) {
      message.error('加载 Agent 简报失败')
      return
    }
    setBrief(data)
  }

  useEffect(() => {
    void load(false)
    return () => kernelStreamAbortRef.current?.abort()
  }, [])

  useEffect(() => {
    const pending = coachNudges.filter(
      (nudge) => nudge.status === 'pending' && !markedCoachNudgeIds.current.has(nudge.id),
    )
    if (pending.length === 0) return
    for (const nudge of pending) {
      markedCoachNudgeIds.current.add(nudge.id)
    }

    void markPendingCoachNudgesShown(pending).then((shownNudges) => {
      const shownById = new Map(shownNudges.map((nudge) => [nudge.id, nudge]))
      for (const nudge of pending) {
        if (!shownById.has(nudge.id)) {
          markedCoachNudgeIds.current.delete(nudge.id)
        }
      }
      if (shownById.size === 0) return
      setCoachNudges((current) => current.map((nudge) => (
        shownById.has(nudge.id) ? { ...nudge, ...shownById.get(nudge.id) } : nudge
      )))
    })
  }, [coachNudges])

  const openDraft = async (action: AgentAction) => {
    setDraftLoading(true)
    const data = await getAgentActionDraft(action.id, useLlm)
    setDraftLoading(false)
    if (!data) {
      message.error('生成行动草案失败，请刷新后重试')
      return
    }
    if (!data.requires_confirmation) {
      void recordAgentActionFeedback(action.id, { outcome: 'accepted', notes: '从 Agent 页面跳转执行' })
      navigate(data.draft.route || action.route)
      return
    }
    setDraft(data)
  }

  const confirmDraft = async () => {
    if (!draft) return
    setExecuteLoading(true)
    const result = await executeAgentAction(draft.action.id, useLlm)
    setExecuteLoading(false)
    if (!result) {
      message.error('执行行动失败，请刷新后重试')
      return
    }
    message.success(result.status === 'created' ? '已创建今日任务' : '已记录行动')
    setDraft(null)
    await load()
    if (result.route) navigate(result.route)
  }

  const runAgent = async (agent: 'study_plan' | 'review' | 'chat') => {
    setAgentLoading(agent)
    const payload = agent === 'chat' ? { tool: 'search_notes', query: '', limit: 5 } : {}
    const result = await triggerAgentTask(agent, agent === 'chat' ? 'search_notes' : 'run', payload)
    setAgentLoading(null)
    if (!result) {
      message.error('Agent 任务执行失败')
      return
    }
    setRuntime(result.runtime)
    message.success(result.result.summary)
    await loadRuntime()
    if (agent !== 'chat') await load()
  }

  const runKernel = async (resumeFromJobId?: string) => {
    setKernelLoading(resumeFromJobId || 'new')
    const prepared = await prepareAgentKernel(resumeFromJobId)
    const jobId = String(prepared?.job?.id || '')
    if (!jobId) {
      setKernelLoading(null)
      message.error('AgentKernel 任务准备失败，请稍后重试')
      return
    }
    setActiveKernelJobId(jobId)
    await loadRuntime()
    const streamPromise = watchKernelJob(jobId)
    const result = await runPreparedAgentKernel(jobId)
    setKernelLoading(null)
    if (!result) {
      message.error('AgentKernel 运行未完成；任务记录已保留，请刷新查看状态')
      await loadRuntime()
      return
    }
    if (result.status === 'completed') {
      message.success(result.strategy || 'AgentKernel 已完成证据检索与行动建议')
    } else if (result.status === 'fallback' && result.fallback?.source === 'rules') {
      message.info('证据型 Kernel 暂未完成，已提供稳定规则简报；你可以先执行其中一步，或稍后从记录继续')
    } else if (result.status === 'unavailable') {
      message.warning('当前未配置可用的 Agent 模型；运行记录已保留，可稍后继续')
    } else if (result.status === 'cancelled') {
      message.info('AgentKernel 已取消，没有执行写入')
    } else if (result.error === 'daily_cost_budget_exceeded') {
      message.warning('今日 AgentKernel 预算已用完，没有继续调用模型；预算按 UTC 每日重置，现有运行记录仍可回放')
    } else if (result.error === 'cost_budget_exceeded') {
      message.warning('本次 AgentKernel 运行已达到成本上限，没有继续调用模型；checkpoint 和运行记录已保留')
    } else {
      message.warning('AgentKernel 未完成；运行记录已保留，可沿用原目标安全重试')
    }
    await streamPromise
    await loadRuntime()
  }

  const watchKernelJob = async (jobId: string) => {
    kernelStreamAbortRef.current?.abort()
    const controller = new AbortController()
    kernelStreamAbortRef.current = controller
    setKernelTraceJobId(jobId)
    setKernelTrace([])

    const outcome = await streamAgentJobEvents(jobId, {
      onSnapshot: (job) => {
        if (['pending', 'running', 'cancelling'].includes(String(job.status || ''))) {
          setActiveKernelJobId(jobId)
        }
      },
      onLog: (log) => {
        const logId = String(log.id || '')
        setKernelTrace((current) => (
          logId && current.some((item) => String(item.id || '') === logId)
            ? current
            : [...current, log].slice(-40)
        ))
      },
      onTerminal: () => setActiveKernelJobId((current) => current === jobId ? null : current),
      onTimeout: () => message.info('实时跟踪窗口已结束；任务仍会保留，可稍后重新打开回放'),
      onError: () => message.warning('实时步骤暂时不可用；任务执行和持久化不受影响'),
    }, controller.signal)

    if (kernelStreamAbortRef.current === controller) kernelStreamAbortRef.current = null
    if (outcome === 'terminal') await loadRuntime()
    return outcome
  }

  const cancelRuntimeJob = async (jobId: string) => {
    const result = await cancelAgentJob(jobId)
    if (!result) {
      message.error('取消请求失败')
      return
    }
    message.info(result.changed ? '已请求取消，当前只读步骤结束后停止' : '该运行已在取消或已经结束')
    await loadRuntime()
  }

  const executePreparedKernelAction = async (prepared: AgentKernelActionDraftResponse) => {
    setExecuteLoading(true)
    const result = await confirmAgentKernelAction(
      prepared.job_id,
      prepared.action.id,
      prepared.draft_id,
    )
    setExecuteLoading(false)
    if (!result) {
      message.error('行动确认失败；没有写入任务，请刷新后重试')
      return
    }
    setKernelActionDraft(null)
    if (result.idempotent) {
      message.info('这条行动已经确认过，没有重复创建')
    } else if (result.status === 'created') {
      message.success('已按确认草案创建任务')
    } else if (result.status === 'skipped_duplicate') {
      message.info('同名今日任务已存在，没有重复创建')
    } else {
      message.success('已记录行动，正在打开执行页面')
    }
    await loadRuntime()
    if (result.route) navigate(result.route)
  }

  const openKernelActionDraft = async (jobId: string, action: AgentAction) => {
    const loadingKey = `${jobId}:${action.id}`
    setKernelActionLoading(loadingKey)
    const prepared = await prepareAgentKernelAction(jobId, action.id)
    setKernelActionLoading(null)
    if (!prepared) {
      message.error('Kernel 行动草案暂不可用；可继续使用上方稳定行动建议')
      return
    }
    if (prepared.status === 'completed' && prepared.execution_result) {
      message.info('这条行动已经确认过，没有重复执行')
      await loadRuntime()
      if (prepared.execution_result.route) navigate(prepared.execution_result.route)
      return
    }
    if (!prepared.requires_confirmation) {
      await executePreparedKernelAction(prepared)
      return
    }
    setKernelActionDraft(prepared)
  }

  const saveProactiveReviewChecks = async (enabled: boolean) => {
    setProactiveSaving(true)
    const saved = await updateCoachPreferences({
      enabled: enabled ? true : proactiveRuntime?.preference.enabled,
      proactive_enabled: enabled,
    })
    setProactiveSaving(false)
    if (!saved) {
      message.error('主动检查设置保存失败，请稍后重试')
      return
    }
    await loadProactiveRuntime()
    message.success(enabled ? '已开启低频复习检查；不会自动修改学习数据' : '已关闭后台复习检查')
  }

  const requestProactiveReviewChecks = (enabled: boolean) => {
    if (!enabled) {
      void saveProactiveReviewChecks(false)
      return
    }
    Modal.confirm({
      title: '开启后台复习检查？',
      content: '系统会低频检查是否有复习积压，只在 Agent 面板准备一条可选建议。它不会自动创建任务、修改计划或开始番茄钟。',
      okText: '开启检查',
      cancelText: '暂不开启',
      onOk: () => saveProactiveReviewChecks(true),
    })
  }

  const openGoalFocusDraft = async () => {
    const focus = goalContext?.today_focus
    if (!focus) return
    if (!focus.requires_confirmation) {
      navigate(focus.route || '/agent')
      return
    }
    setDraftLoading(true)
    const data = await getAgentGoalContextActionDraft(focus.action_id)
    setDraftLoading(false)
    if (!data) {
      message.error('生成目标行动草案失败，请刷新后重试')
      return
    }
    setDraft(data)
  }

  const sendCoachFeedback = async (nudge: CoachNudge, outcome: CoachFeedbackOutcome) => {
    const result = await recordCoachNudgeFeedback(nudge.id, { outcome })
    if (!result) {
      message.error('Coach 反馈记录失败')
      return false
    }
    const outcomeMessage: Partial<Record<CoachFeedbackOutcome, string>> = {
      accepted: '已采纳建议；准备好后再开始行动',
      started: '已开始行动；完成后记得回来确认',
      completed: '已记录完成，Coach 会据此调整后续建议',
      abandoned: '已记录本次未继续，Coach 会避免重复施压',
    }
    message.success(outcomeMessage[outcome] || '已记录 Coach 反馈')
    setCoachNudges((current) => current.map((item) => (
      item.id === nudge.id ? { ...item, status: result.status as CoachNudge['status'] } : item
    )))
    setAssociationResult((current) => current?.nudge?.id === nudge.id
      ? { ...current, nudge: { ...current.nudge, status: result.status } }
      : current)
    await loadCoachNudges()
    return true
  }

  const restoreAssociationFromNudge = (nudge: CoachNudge) => {
    const associations = nudge.explainability?.associations
    if (!Array.isArray(associations) || associations.length === 0) return false
    setAssociationResult({
      associations,
      event: nudge.event_id
        ? { id: nudge.event_id, event_type: 'association.recalled' }
        : null,
      nudge: {
        id: nudge.id,
        skill_id: nudge.skill_id,
        title: nudge.title,
        body: nudge.body,
        status: nudge.status,
        suggested_action: nudge.suggested_action,
        explainability: nudge.explainability,
      },
    })
    setExpandedAssociationIds(new Set())
    return true
  }

  const startCoachNudge = async (nudge: CoachNudge) => {
    const started = await startCoachNudgeAction(nudge.id)
    if (!started) {
      message.error('无法开始这条 Coach 建议，请刷新后重试')
      return
    }
    const activeNudge = {
      ...nudge,
      ...started.nudge,
      action_attempt: started.attempt,
    } as CoachNudge
    setCoachNudges((current) => current.map((item) => (
      item.id === nudge.id ? activeNudge : item
    )))
    setAssociationResult((current) => current?.nudge?.id === nudge.id
      ? { ...current, nudge: { ...current.nudge, status: activeNudge.status } }
      : current)
    message.success(started.idempotent ? '继续这条 Coach 行动' : '已开始行动；完成后会自动关联真实学习行为')
    if (activeNudge.skill_id === 'association_recall' && restoreAssociationFromNudge(activeNudge)) return
    const route = activeNudge.route || activeNudge.suggested_action?.route
    if (route) navigate(routeWithCoachAttempt(route, started.attempt, nudge.id))
  }

  const showCoachReplay = async (nudge: CoachNudge) => {
    setCoachReplayLoading(true)
    const replay = await getCoachNudgeReplay(nudge.id)
    setCoachReplayLoading(false)
    if (!replay) {
      message.error('暂时无法读取这条 Coach 回放')
      return
    }
    setCoachReplay(replay)
  }

  const recallAssociations = async () => {
    const text = associationText.trim()
    if (!text) {
      message.warning('请输入要联想的学习内容')
      return
    }
    setAssociationLoading(true)
    try {
      const result = await findConceptAssociations(text)
      setAssociationResult(result)
      setExpandedAssociationIds(new Set())
      if (result.nudge) {
        setCoachNudges((current) => (
          current.some((item) => item.id === result.nudge?.id)
            ? current
            : [result.nudge as CoachNudge, ...current]
        ))
        if (!associationShownNudgeIds.current.has(result.nudge.id)) {
          associationShownNudgeIds.current.add(result.nudge.id)
          const shown = await markCoachNudgeShown(result.nudge.id)
          if (!shown) {
            associationShownNudgeIds.current.delete(result.nudge.id)
          } else {
            setCoachNudges((current) => current.map((item) => (
              item.id === shown.id ? { ...item, ...shown } : item
            )))
            setAssociationResult((current) => current?.nudge?.id === shown.id
              ? { ...current, nudge: { ...current.nudge, status: shown.status } }
              : current)
          }
        }
      }
      if (result.associations.length === 0) {
        message.info('暂未找到带有历史证据的关联')
      }
    } catch {
      message.error('联想请求失败，请稍后重试')
    } finally {
      setAssociationLoading(false)
    }
  }

  const recordAssociationFeedback = async (outcome: CoachFeedbackOutcome) => {
    const nudgeId = associationResult?.nudge?.id
    if (!nudgeId || associationFeedbackIds.current.has(`${nudgeId}:${outcome}`)) return
    associationFeedbackIds.current.add(`${nudgeId}:${outcome}`)
    const result = await recordCoachNudgeFeedback(nudgeId, { outcome })
    if (!result) {
      associationFeedbackIds.current.delete(`${nudgeId}:${outcome}`)
      message.error('Coach 反馈记录失败')
      return
    }
    setCoachNudges((current) => current.map((item) => (
      item.id === nudgeId ? { ...item, status: result.status as CoachNudge['status'] } : item
    )))
    if (outcome === 'completed') {
      message.success('已记录这次联想处理')
      setAssociationResult((current) => current ? {
        ...current,
        nudge: current.nudge ? { ...current.nudge, status: 'completed' } : null,
      } : current)
    } else {
      setAssociationResult((current) => current ? {
        ...current,
        nudge: current.nudge ? { ...current.nudge, status: result.status } : null,
      } : current)
    }
  }

  const renderAssociation = (association: ConceptAssociation) => {
    const expanded = expandedAssociationIds.has(association.concept_id)
    const evidenceItems = [
      ...(association.evidence?.notes || []).map((item) => ({ ...item, type: '笔记' })),
      ...(association.evidence?.wrong_questions || []).map((item) => ({ ...item, type: '错题' })),
      ...(association.prerequisites || []).flatMap((item) => [
        ...(item.evidence?.notes || []).map((source) => ({ ...source, type: `先修笔记：${item.name}` })),
        ...(item.evidence?.wrong_questions || []).map((source) => ({ ...source, type: `先修错题：${item.name}` })),
      ]),
    ]
    return (
      <List.Item
        actions={[
          <Button
            key="evidence"
            size="small"
            onClick={() => {
              const next = new Set(expandedAssociationIds)
              if (next.has(association.concept_id)) next.delete(association.concept_id)
              else next.add(association.concept_id)
              setExpandedAssociationIds(next)
              if (!expanded) void recordAssociationFeedback('accepted')
            }}
          >
            {expanded ? '收起依据' : '查看依据'}
          </Button>,
        ]}
      >
        <Space direction="vertical" size={4} style={{ width: '100%' }}>
          <Space wrap>
            <Tag color="blue">{association.concept_name}</Tag>
            <Tag>掌握度 {Math.round(Number(association.mastery || 0))}%</Tag>
          </Space>
          <Text type="secondary">{association.reason || '存在相关历史证据'}</Text>
          {expanded && (
            <Space direction="vertical" size={2}>
              {evidenceItems.length > 0 ? evidenceItems.map((item) => (
                <Text key={`${item.type}-${item.id}`} type="secondary">
                  {item.type}：{item.title || item.knowledge_point || item.id}
                </Text>
              )) : <Text type="secondary">暂无可展开的直接证据。</Text>}
            </Space>
          )}
        </Space>
      </List.Item>
    )
  }

  const runMemoryLearning = async () => {
    setMemoryActionLoading('run')
    const result = await runAgentMemoryLearning()
    setMemoryActionLoading(null)
    if (!result) {
      message.error('长期记忆学习失败，请稍后重试')
      return
    }
    message.success(result.message || `已检查长期记忆：确认 ${result.confirmed ?? 0}，待确认 ${result.staged ?? 0}`)
    await loadAgentMemoryReview()
  }

  const confirmMemoryCandidate = async (candidate: AgentMemoryCandidate, lock = false) => {
    setMemoryActionLoading(candidate.id)
    const result = await confirmAgentMemoryCandidate(candidate.id, { lock })
    setMemoryActionLoading(null)
    if (!result) {
      message.error('确认记忆失败，请稍后重试')
      return
    }
    message.success(lock ? '已确认并锁定这条长期记忆' : '已确认这条长期记忆')
    await loadAgentMemoryReview()
  }

  const ignoreMemoryCandidate = async (candidate: AgentMemoryCandidate, reason: 'ignored' | 'inaccurate') => {
    setMemoryActionLoading(candidate.id)
    const result = await ignoreAgentMemoryCandidate(candidate.id, { reason })
    setMemoryActionLoading(null)
    if (!result) {
      message.error('更新待确认记忆失败，请稍后重试')
      return
    }
    message.success(reason === 'inaccurate' ? '已标记为不准确' : '已忽略这条记忆')
    await loadAgentMemoryReview()
  }

  const tasks = brief?.context?.tasks || {}
  const review = brief?.context?.review || {}
  const learning = brief?.context?.learning || {}
  const memory = brief?.context?.memory || {}
  const personalization = brief?.context?.personalization
  const feedbackStats = personalization?.feedback_stats

  const controlProfileItem = async (item: AgentPersonalizationItem, operation: 'ignore' | 'inaccurate' | 'lock' | 'unlock' | 'restore') => {
    const result = await controlAgentProfileItem(item.id, operation)
    if (!result) {
      message.error('画像操作失败，请刷新后重试')
      return
    }
    message.success('已更新画像控制，Agent 下次会参考')
    await load()
  }

  const renderProfileAction = (item: AgentPersonalizationItem, operation: 'ignore' | 'inaccurate' | 'lock' | 'unlock' | 'restore', danger = false) => (
    <Popconfirm
      key={operation}
      title={profileOperationCopy[operation].title}
      description="这只会影响 Agent 如何理解你和排序建议，可随时恢复。"
      okText="确认"
      cancelText="取消"
      onConfirm={() => void controlProfileItem(item, operation)}
    >
      <Button size="small" danger={danger}>{profileOperationCopy[operation].label}</Button>
    </Popconfirm>
  )

  const renderProfileItem = (item: AgentPersonalizationItem) => (
    <List.Item
      actions={[
        item.locked ? renderProfileAction(item, 'unlock') : renderProfileAction(item, 'lock'),
        renderProfileAction(item, 'inaccurate'),
        renderProfileAction(item, 'ignore', true),
        (item.ignored || item.inaccurate) ? renderProfileAction(item, 'restore') : null,
      ].filter(Boolean)}
    >
      <Space direction="vertical" size={2}>
        <Space wrap>
          <Text>{item.text}</Text>
          {item.source && <Tag>{item.source}</Tag>}
          {item.locked && <Tag color="gold">已锁定</Tag>}
          {item.inaccurate && <Tag color="red">不准确</Tag>}
          {item.ignored && <Tag color="default">已忽略</Tag>}
        </Space>
        {item.confidence !== undefined && <Text type="secondary">置信度：{Math.round(Number(item.confidence) * 100)}%</Text>}
      </Space>
    </List.Item>
  )

  const renderMemoryCandidate = (candidate: AgentMemoryCandidate) => {
    const evidence = parseEvidence(candidate.evidence)
    return (
      <List.Item
        actions={[
          <Button
            key="confirm"
            size="small"
            type="primary"
            icon={<CheckCircleOutlined />}
            loading={memoryActionLoading === candidate.id}
            onClick={() => void confirmMemoryCandidate(candidate)}
          >
            确认
          </Button>,
          <Button
            key="lock"
            size="small"
            icon={<LockOutlined />}
            loading={memoryActionLoading === candidate.id}
            onClick={() => void confirmMemoryCandidate(candidate, true)}
          >
            确认并锁定
          </Button>,
          <Popconfirm
            key="inaccurate"
            title="把这条候选记忆标记为不准确？"
            description="Agent 不会把它加入长期记忆。"
            okText="标记"
            cancelText="取消"
            onConfirm={() => void ignoreMemoryCandidate(candidate, 'inaccurate')}
          >
            <Button size="small" danger icon={<CloseCircleOutlined />} loading={memoryActionLoading === candidate.id}>
              不准确
            </Button>
          </Popconfirm>,
          <Popconfirm
            key="ignore"
            title="忽略这条候选记忆？"
            description="它会从待确认列表移除，不影响其他记忆。"
            okText="忽略"
            cancelText="取消"
            onConfirm={() => void ignoreMemoryCandidate(candidate, 'ignored')}
          >
            <Button size="small" loading={memoryActionLoading === candidate.id}>忽略</Button>
          </Popconfirm>,
        ]}
      >
        <Space direction="vertical" size={6} style={{ width: '100%' }}>
          <Space wrap>
            <Text strong>{candidate.memory_value}</Text>
            <Tag color="blue">{candidate.category || 'memory'}</Tag>
            {candidate.memory_type && <Tag>{candidate.memory_type}</Tag>}
            <Tag color="gold">置信度 {confidenceLabel(candidate.confidence)}</Tag>
            {candidate.source_type && <Tag color="purple">{candidate.source_type}{candidate.source_id ? ` #${candidate.source_id}` : ''}</Tag>}
          </Space>
          {evidence.length > 0 && (
            <Space wrap>
              {evidence.slice(0, 4).map((item) => <Tag key={item}>{item}</Tag>)}
            </Space>
          )}
          {candidate.expires_at && <Text type="secondary">有效期至：{candidate.expires_at}</Text>}
        </Space>
      </List.Item>
    )
  }

  const sendFeedback = async (action: AgentAction, outcome: 'helpful' | 'later' | 'useless' | 'dismissed', reasonCode?: AgentNegativeReasonCode) => {
    const notesMap = {
      helpful: '用户认为该建议有帮助',
      later: '用户选择稍后再处理该建议',
      useless: '用户认为该建议无用',
      dismissed: '用户拒绝该建议',
    }
    const result = await recordAgentActionFeedback(action.id, {
      outcome,
      notes: reasonCode ? `${notesMap[outcome]}：${negativeReasonOptions.find((item) => item.key === reasonCode)?.label || reasonCode}` : notesMap[outcome],
      effectiveness: outcome === 'helpful' ? 0.9 : outcome === 'later' ? 0.45 : 0.1,
      reason_code: reasonCode,
    })
    if (!result) {
      message.error('反馈记录失败')
      return
    }
    message.success('已记录反馈，Agent 下次会参考')
    await load()
  }

  const negativeFeedbackMenu = (action: AgentAction, outcome: 'later' | 'useless' | 'dismissed') => ({
    items: negativeReasonOptions.map((reason) => ({ key: reason.key, label: reason.label })),
    onClick: ({ key }: { key: string }) => void sendFeedback(action, outcome, key as AgentNegativeReasonCode),
  })

  const supportingCount = (items?: AgentGoalContextItem[]) => (items || []).length

  return (
    <PageShell
      title={<><ExperimentOutlined style={{ marginRight: 8 }} />自主学习 Agent</>}
      onBack={() => navigate('/')}
      rightExtra={(
        <Space>
          <Text type="secondary">高级规划</Text>
          <Switch
            checked={useLlm}
            onChange={(checked) => {
              setUseLlm(checked)
              void load(checked)
            }}
          />
          <Button onClick={() => setShowDebug((v) => !v)}>
            {showDebug ? '隐藏调试' : '显示调试'}
          </Button>
          <Button loading={loading} onClick={() => void load()}>刷新感知</Button>
        </Space>
      )}
    >
      <Space direction="vertical" size={12} style={{ width: '100%' }}>
        <Alert
          type={brief?.risk_level === 'high' ? 'error' : brief?.risk_level === 'medium' ? 'warning' : 'success'}
          showIcon
          message={brief?.current_focus || 'Agent 正在观察你的学习状态'}
          description={brief?.state_summary || '暂无简报，请刷新后查看。'}
        />

        <ProactiveReviewChecksCard
          status={proactiveRuntime}
          saving={proactiveSaving}
          onChange={requestProactiveReviewChecks}
        />

        {brief?.planner?.source === 'llm' && (
          <Alert
            type="info"
            showIcon
            message={`LLM Planner：${brief.planner.strategy || '已启用增强规划'}`}
            description={brief.planner.fallback_plan ? `保底方案：${brief.planner.fallback_plan}` : undefined}
          />
        )}

        <WeeklyLearningReportCard
          report={weeklyReport}
          loading={weeklyReportLoading}
          onGenerate={() => void loadWeeklyReport()}
          onNavigate={navigate}
        />

        <Card
          size="small"
          loading={loading}
          title="当前目标"
          extra={<Button size="small" onClick={() => navigate(goalContext?.active_goal?.route || goalContext?.goal_creation?.route || '/goals')}>打开目标</Button>}
        >
          {goalContext?.active_goal ? (
            <Space direction="vertical" size={12} style={{ width: '100%' }}>
              <Row gutter={[12, 12]}>
                <Col xs={24} md={9}>
                  <Space direction="vertical" size={4}>
                    <Space wrap>
                      <Text strong>{goalContext.active_goal.title}</Text>
                      {goalContext.active_goal.deadline && <Tag color="blue">截止 {goalContext.active_goal.deadline}</Tag>}
                      {goalContext.active_goal.target_level && <Tag>{goalContext.active_goal.target_level}</Tag>}
                    </Space>
                    <Space wrap>
                      <Tag>待办 {goalContext.active_goal.progress?.pending_task_count ?? 0}</Tag>
                      <Tag color={goalContext.active_goal.progress?.today_task_count ? 'green' : 'default'}>今日 {goalContext.active_goal.progress?.today_task_count ?? 0}</Tag>
                      <Tag color={goalContext.active_goal.progress?.overdue_task_count ? 'red' : 'default'}>过期 {goalContext.active_goal.progress?.overdue_task_count ?? 0}</Tag>
                      <Tag color="cyan">已完成 {goalContext.active_goal.progress?.completed_today_count ?? 0}</Tag>
                    </Space>
                  </Space>
                </Col>
                <Col xs={24} md={8}>
                  <Space direction="vertical" size={4}>
                    <Text type="secondary">今天最小且有用的一步</Text>
                    <Text strong>{goalContext.today_focus?.title}</Text>
                    <Text type="secondary">{goalContext.today_focus?.estimated_minutes} 分钟 · {goalContext.today_focus?.reason}</Text>
                  </Space>
                </Col>
                <Col xs={24} md={7}>
                  <Space direction="vertical" size={6} style={{ width: '100%' }}>
                    <Space wrap>
                      {goalContext.risk_flags?.no_daily_plan && <Tag color="orange">无今日计划</Tag>}
                      {goalContext.risk_flags?.review_debt_high && <Tag color="red">复习积压高</Tag>}
                      {goalContext.risk_flags?.goal_stale && <Tag color="gold">目标偏久未推进</Tag>}
                      {!goalContext.risk_flags?.no_daily_plan && !goalContext.risk_flags?.review_debt_high && !goalContext.risk_flags?.goal_stale && <Tag color="green">无高风险信号</Tag>}
                    </Space>
                    <Button
                      type="primary"
                      size="small"
                      loading={draftLoading}
                      onClick={() => void openGoalFocusDraft()}
                    >
                      {goalContext.today_focus?.requires_confirmation ? '生成草案' : '开始行动'}
                    </Button>
                  </Space>
                </Col>
              </Row>

              <Row gutter={[12, 12]}>
                <Col xs={24} md={12}>
                  <Text strong>判断依据</Text>
                  <Space wrap style={{ marginTop: 8 }}>
                    {(goalContext.evidence || []).map((item) => <Tag key={item}>{item}</Tag>)}
                  </Space>
                </Col>
                <Col xs={24} md={12}>
                  <Text strong>相关上下文</Text>
                  <Space wrap style={{ marginTop: 8 }}>
                    <Tag color={supportingCount(goalContext.supporting_context?.notes) ? 'blue' : 'default'}>笔记 {supportingCount(goalContext.supporting_context?.notes)}</Tag>
                    <Tag color={supportingCount(goalContext.supporting_context?.materials) ? 'purple' : 'default'}>资料 {supportingCount(goalContext.supporting_context?.materials)}</Tag>
                    <Tag color={supportingCount(goalContext.supporting_context?.wrong_questions) ? 'red' : 'default'}>错题 {supportingCount(goalContext.supporting_context?.wrong_questions)}</Tag>
                    <Tag color={supportingCount(goalContext.supporting_context?.review_items) ? 'orange' : 'default'}>复习 {supportingCount(goalContext.supporting_context?.review_items)}</Tag>
                  </Space>
                  <List
                    size="small"
                    dataSource={[
                      ...(goalContext.supporting_context?.notes || []).slice(0, 2).map((item) => ({ ...item, _kind: '笔记' })),
                      ...(goalContext.supporting_context?.wrong_questions || []).slice(0, 2).map((item) => ({ ...item, _kind: '错题' })),
                    ]}
                    locale={{ emptyText: '暂未找到直接支持该目标的笔记或错题。' }}
                    renderItem={(item) => (
                      <List.Item>
                        <Space wrap>
                          <Tag>{String(item._kind || '证据')}</Tag>
                          <Text>{String(item.title || item.id || '-')}</Text>
                        </Space>
                      </List.Item>
                    )}
                  />
                </Col>
              </Row>
            </Space>
          ) : (
            <Alert
              type="info"
              showIcon
              message={goalContext?.goal_creation?.title || '创建当前主目标'}
              description={goalContext?.goal_creation?.message || '当前没有活跃目标。先创建一个目标后，Agent 会把任务、笔记、错题和复习证据组织到同一个 cockpit。'}
              action={<Button size="small" type="primary" onClick={() => navigate('/goals')}>创建目标</Button>}
            />
          )}
        </Card>

        <CoachNudgesPanel
          nudges={coachNudges}
          replay={coachReplay}
          replayLoading={coachReplayLoading}
          onRefresh={() => void loadCoachNudges()}
          onFeedback={sendCoachFeedback}
          onStart={startCoachNudge}
          onShowReplay={showCoachReplay}
          onCloseReplay={() => setCoachReplay(null)}
        />

        <Card
          size="small"
          title="知识联想"
          extra={<Tag color={associationResult?.associations.length ? 'blue' : 'default'}>显式请求</Tag>}
        >
          <Space direction="vertical" size={10} style={{ width: '100%' }}>
            <Text type="secondary">粘贴正在学习的内容，查看与已有概念、笔记和错题的关联。不会自动创建任务或修改知识状态。</Text>
            <Input.TextArea
              value={associationText}
              rows={3}
              maxLength={2000}
              showCount
              placeholder="例如：今天开始学贝叶斯定理，公式有点绕。"
              onChange={(event) => setAssociationText(event.target.value)}
            />
            <Button type="primary" loading={associationLoading} onClick={() => void recallAssociations()}>
              查找关联
            </Button>
            {associationResult && (
              <List
                size="small"
                header={associationResult.associations.length > 0 ? '可追溯的旧知识关联' : undefined}
                dataSource={associationResult.associations}
                locale={{ emptyText: '没有达到证据门槛的关联。' }}
                renderItem={renderAssociation}
              />
            )}
            {associationResult?.nudge && associationResult.nudge.status !== 'completed' && (
              <Button size="small" onClick={() => void recordAssociationFeedback('completed')}>
                已处理这次联想
              </Button>
            )}
          </Space>
        </Card>

        <Row gutter={[12, 12]}>
          <Col xs={24} md={8}>
            <Card size="small" loading={loading}>
              <Text type="secondary">自主等级</Text>
              <div style={{ marginTop: 8 }}>
                <Tag color="blue">{autonomyLabel(brief?.autonomy_level)}</Tag>
              </div>
              <Paragraph type="secondary" style={{ marginTop: 8, marginBottom: 0 }}>
                根据学习天数、长期记忆数量和行为数据动态判断。
              </Paragraph>
            </Card>
          </Col>
          <Col xs={24} md={8}>
            <Card size="small" loading={loading}>
              <Text type="secondary">准备度</Text>
              <Progress percent={Math.round(brief?.readiness_score || 0)} status={brief?.risk_level === 'high' ? 'exception' : 'normal'} />
            </Card>
          </Col>
          <Col xs={24} md={8}>
            <Card size="small" loading={loading}>
              <Text type="secondary">风险等级</Text>
              <div style={{ marginTop: 8 }}><Tag color={riskColor(brief?.risk_level)}>{brief?.risk_level || '-'}</Tag></div>
              <Paragraph type="secondary" style={{ marginTop: 8, marginBottom: 0 }}>
                由复习积压、过期任务、今日启动情况和走神率综合判断。
              </Paragraph>
            </Card>
          </Col>
        </Row>

        <Card
          size="small"
          title={<><UserOutlined style={{ marginRight: 8 }} />长期记忆审核</>}
          loading={memoryReviewLoading}
          extra={(
            <Space>
              <Tag color={memoryCandidates.length ? 'gold' : 'green'}>待确认 {memoryCandidates.length}</Tag>
              <Button
                size="small"
                icon={<ReloadOutlined />}
                loading={memoryActionLoading === 'run'}
                onClick={() => void runMemoryLearning()}
              >
                运行学习
              </Button>
            </Space>
          )}
        >
          <Space direction="vertical" size={12} style={{ width: '100%' }}>
            <Row gutter={[12, 12]}>
              <Col xs={24} md={9}>
                <Space direction="vertical" size={4}>
                  <Text type="secondary">Core Profile</Text>
                  <Text strong>{coreProfile ? `更新于 ${coreProfile.updated_at || '-'}` : '暂无核心画像'}</Text>
                  <Text type="secondary">只汇总高置信长期信号，不包含原始笔记正文或敏感材料。</Text>
                </Space>
              </Col>
              <Col xs={24} md={15}>
                {coreProfileLines(coreProfile).length > 0 ? (
                  <Space wrap>
                    {coreProfileLines(coreProfile).slice(0, 8).map((line) => (
                      <Tag key={line} color="cyan">{line}</Tag>
                    ))}
                  </Space>
                ) : (
                  <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="继续学习、反馈和整理笔记后会生成核心画像" />
                )}
              </Col>
            </Row>
            <List
              size="small"
              dataSource={memoryCandidates}
              locale={{ emptyText: '没有待确认记忆。低风险聚合记忆会自动提交；敏感或主观推断会在这里等待你确认。' }}
              renderItem={renderMemoryCandidate}
            />
          </Space>
        </Card>

        <Card size="small" title={<><UserOutlined style={{ marginRight: 8 }} />我对你的了解</>} loading={loading}>
          <Space direction="vertical" size={10} style={{ width: '100%' }}>
            <div>
              <Text strong>画像摘要：</Text>
              <List
                size="small"
                dataSource={personalization?.summary_items || []}
                locale={{ emptyText: '暂无足够画像。继续使用任务、复习、错题和反馈后，Agent 会逐步了解你的学习节奏。' }}
                renderItem={renderProfileItem}
              />
            </div>
            <div>
              <Text strong>最近学到的偏好：</Text>
              <List
                size="small"
                dataSource={personalization?.preference_items || []}
                locale={{ emptyText: '暂无可控偏好。' }}
                renderItem={renderProfileItem}
              />
            </div>
            {(personalization?.feedback_impacts || []).length > 0 && (
              <div>
                <Text strong>最近反馈影响：</Text>
                <Space wrap style={{ marginTop: 6 }}>
                  {personalization?.feedback_impacts?.map((impact) => (
                    <Tag key={`${impact.dimension}-${impact.key}`} color={impact.effect === 'deprioritize' ? 'orange' : 'green'}>{impact.message}</Tag>
                  ))}
                </Space>
              </div>
            )}
            <Collapse
              size="small"
              ghost
              items={[{
                key: 'profile-audit',
                label: '我根据你的修正学到了什么 / 画像修正记录',
                children: (
                  <List
                    size="small"
                    dataSource={personalization?.profile_control_logs || runtime?.profile_control_logs || []}
                    locale={{ emptyText: '暂无画像修正记录。你标记“不准确 / 不再使用 / 锁定”后会显示在这里。' }}
                    renderItem={(log) => (
                      <List.Item>
                        <Space direction="vertical" size={2}>
                          <Space wrap>
                            <Tag color="purple">{log.operation_label || log.operation || log.status || '-'}</Tag>
                            <Text type="secondary">{log.item_id}</Text>
                            <Text type="secondary">{log.created_at}</Text>
                          </Space>
                          <Text>{log.item_text || log.message || '已记录你的画像修正，后续建议会参考。'}</Text>
                        </Space>
                      </List.Item>
                    )}
                  />
                ),
              }]}
            />
            <Space wrap>
              <Tag>接受/有帮助：{String(feedbackStats?.accepted ?? 0)}</Tag>
              <Tag>拒绝/稍后/无用：{String(feedbackStats?.rejected_or_delayed ?? 0)}</Tag>
              {feedbackStats?.accepted_rate !== null && feedbackStats?.accepted_rate !== undefined && (
                <Tag color="green">建议接受率：{Math.round(Number(feedbackStats.accepted_rate) * 100)}%</Tag>
              )}
            </Space>
            <List
              size="small"
              header="最近反馈 / Agent 学习记录"
              dataSource={personalization?.recent_feedback || []}
              locale={{ emptyText: '暂无反馈记录。你可以对每条建议点“有帮助 / 稍后 / 无用 / 不再提醒”。' }}
              renderItem={(item) => (
                <List.Item>
                  <Space direction="vertical" size={2}>
                    <Space wrap>
                      <Tag>{item.outcome_label || item.outcome || '-'}</Tag>
                      <Text type="secondary">{item.action_id}</Text>
                      {item.action_type && <Tag>{item.action_type}</Tag>}
                      {item.topic && <Tag color="blue">{item.topic}</Tag>}
                      {item.reason_label && <Tag color="orange">原因：{item.reason_label}</Tag>}
                    </Space>
                    {item.source_signal && <Text type="secondary">影响来源：{item.source_signal}</Text>}
                    {item.notes && <Text>{item.notes}</Text>}
                  </Space>
                </List.Item>
              )}
            />
          </Space>
        </Card>

        <Card
          size="small"
          title={<><ThunderboltOutlined style={{ marginRight: 8 }} />下一步行动</>}
          loading={loading}
        >
          <List
            dataSource={brief?.next_actions || []}
            locale={{ emptyText: '暂无行动建议' }}
            renderItem={(item) => (
              <List.Item
                actions={[
                  <Button
                    key="helpful"
                    size="small"
                    onClick={() => void sendFeedback(item, 'helpful')}
                  >
                    有帮助
                  </Button>,
                  <Dropdown key="later" menu={negativeFeedbackMenu(item, 'later')} trigger={['click']}>
                    <Button size="small">稍后 / 选择原因</Button>
                  </Dropdown>,
                  <Dropdown key="useless" menu={negativeFeedbackMenu(item, 'useless')} trigger={['click']}>
                    <Button size="small" danger>无用 / 选择原因</Button>
                  </Dropdown>,
                  <Dropdown key="dismissed" menu={negativeFeedbackMenu(item, 'dismissed')} trigger={['click']}>
                    <Button size="small" danger>不再提醒 / 原因</Button>
                  </Dropdown>,
                  <Button
                    key="go"
                    size="small"
                    loading={draftLoading}
                    type={item.priority === 'high' ? 'primary' : 'default'}
                    onClick={() => void openDraft(item)}
                  >
                    生成草案
                  </Button>,
                ]}
              >
                <List.Item.Meta
                  title={(
                    <Space wrap>
                      <Tag color={priorityColor(item.priority)}>{item.priority}</Tag>
                      <span>{item.title}</span>
                      <Tag>{item.estimated_minutes} 分钟</Tag>
                    </Space>
                  )}
                  description={(
                    <Space direction="vertical" size={6} style={{ width: '100%' }}>
                      <Text>{item.reason}</Text>
                      <Collapse
                        size="small"
                        ghost
                        items={[{
                          key: 'why',
                          label: '为什么推荐',
                          children: (
                            <Space direction="vertical" size={4}>
                              {item.explainability?.summary && <Alert type="info" showIcon message={item.explainability.summary} />}
                              <Text strong>参考数据</Text>
                              <Space wrap>{(item.explainability?.data_signals || []).map((signal) => <Tag key={signal}>{signal}</Tag>)}</Space>
                              {(item.explainability?.feedback_refs || []).length > 0 && (
                                <>
                                  <Text strong>历史反馈</Text>
                                  <List size="small" dataSource={item.explainability?.feedback_refs || []} renderItem={(ref) => <List.Item>• {ref}</List.Item>} />
                                </>
                              )}
                              {(item.explainability?.reason_adjustments || []).length > 0 && (
                                <Space wrap>
                                  {item.explainability?.reason_adjustments?.map((text) => <Tag key={text} color="geekblue">{text}</Tag>)}
                                </Space>
                              )}
                              {item.explainability?.adjustment && <Text type="secondary">{item.explainability.adjustment}</Text>}
                              {item.explainability?.audit?.write_requires_confirmation && <Tag color="gold">写入型动作：仅生成草案，需你确认后执行</Tag>}
                            </Space>
                          ),
                        }]}
                      />
                    </Space>
                  )}
                />
              </List.Item>
            )}
          />
        </Card>

        <NorthStarMetricsCard
          report={northStarMetrics}
          experiment={coachExperiment}
          onRefresh={() => void loadNorthStarMetrics()}
        />

        <Card size="small" title={<><BulbOutlined style={{ marginRight: 8 }} />关注信号</>} loading={loading}>
          <List
            dataSource={brief?.watch_signals || []}
            renderItem={(item) => <List.Item>• {item}</List.Item>}
          />
        </Card>

        {showDebug && (
          <>
            <Card size="small" title="Agent 感知上下文" loading={loading}>
              <Row gutter={[12, 12]}>
                <Col xs={12} md={6}><Tag>今日任务：{String(tasks.today_task_count ?? 0)}</Tag></Col>
                <Col xs={12} md={6}><Tag>过期任务：{String(tasks.overdue_task_count ?? 0)}</Tag></Col>
                <Col xs={12} md={6}><Tag>到期复习：{String(review.due_review_count ?? 0)}</Tag></Col>
                <Col xs={12} md={6}><Tag>今日学习：{String(learning.today_minutes ?? 0)} 分钟</Tag></Col>
                <Col xs={12} md={6}><Tag>长期记忆：{String(memory.active_memory_count ?? 0)}</Tag></Col>
                <Col xs={12} md={6}><Tag>走神率：{Math.round(Number(learning.recent_distracted_rate ?? 0) * 100)}%</Tag></Col>
              </Row>
            </Card>

            <Card size="small" title="Agent Runtime" loading={loading}>
              <Space direction="vertical" size={12} style={{ width: '100%' }}>
                <Space wrap>
                  <Tag color={runtime?.status === 'running' ? 'processing' : 'default'}>状态：{runtime?.status || 'idle'}</Tag>
                  {runtime?.kernel_daily_budget && (
                    <Tag color={runtime.kernel_daily_budget.remaining_model_calls <= 0 ? 'warning' : 'default'}>
                      今日 Kernel 调用：{runtime.kernel_daily_budget.model_calls}/{runtime.kernel_daily_budget.model_call_limit}
                    </Tag>
                  )}
                  {runtime?.kernel_daily_budget && (
                    <Tag color={runtime.kernel_daily_budget.remaining_estimated_tokens <= 0 ? 'warning' : 'default'}>
                      估算 Token：{runtime.kernel_daily_budget.estimated_tokens.toLocaleString('zh-CN')}/{runtime.kernel_daily_budget.estimated_token_limit.toLocaleString('zh-CN')}
                    </Tag>
                  )}
                  {Boolean(runtime?.kernel_daily_budget?.actual_usage_calls) && (
                    <Tag color="blue">
                      供应商 Token：{Number(runtime?.kernel_daily_budget?.actual_tokens || 0).toLocaleString('zh-CN')}
                    </Tag>
                  )}
                  {Boolean(runtime?.kernel_daily_budget?.configured_cost_usd) && (
                    <Tag color="green">
                      配置单价参考成本：${Number(runtime?.kernel_daily_budget?.configured_cost_usd || 0).toFixed(6)}
                    </Tag>
                  )}
                  {(runtime?.agents || []).map((agent) => (
                    <Button
                      key={agent.name}
                      size="small"
                      loading={agentLoading === agent.name}
                      onClick={() => void runAgent(agent.name as 'study_plan' | 'review' | 'chat')}
                    >
                      触发 {agent.display_name}
                    </Button>
                  ))}
                  <Button
                    size="small"
                    type="primary"
                    ghost
                    loading={kernelLoading === 'new'}
                    disabled={Boolean(activeKernelJobId)}
                    onClick={() => void runKernel()}
                  >
                    运行证据型 AgentKernel
                  </Button>
                  {activeKernelJobId && (
                    <Button danger size="small" onClick={() => void cancelRuntimeJob(activeKernelJobId)}>
                      取消当前运行
                    </Button>
                  )}
                </Space>
                {kernelTraceJobId && (
                  <List
                    size="small"
                    bordered
                    header={(
                      <Space wrap>
                        <Text strong>AgentKernel 实时步骤 / 持久回放</Text>
                        <Tag>{kernelTraceJobId.slice(0, 12)}</Tag>
                      </Space>
                    )}
                    dataSource={kernelTrace}
                    locale={{ emptyText: '任务已连接，等待第一个持久化步骤…' }}
                    renderItem={(log) => {
                      const metadata = log.metadata && typeof log.metadata === 'object'
                        ? log.metadata as Record<string, unknown>
                        : {}
                      const step = metadata.step && typeof metadata.step === 'object'
                        ? metadata.step as Record<string, unknown>
                        : {}
                      return (
                        <List.Item>
                          <Space direction="vertical" size={2}>
                            <Space wrap>
                              <Tag color={log.status === 'failed' ? 'red' : log.status === 'finish' ? 'green' : ['cancelled', 'interrupted'].includes(String(log.status || '')) ? 'orange' : 'blue'}>
                                {String(log.status || '-')}
                              </Tag>
                              {Boolean(step.tool) && <Tag>{String(step.tool)}</Tag>}
                              <Text type="secondary">{String(log.created_at || '')}</Text>
                            </Space>
                            <Text>{String(log.message || '')}</Text>
                            {Boolean(step.observation_preview) && (
                              <Text type="secondary">证据摘要：{String(step.observation_preview)}</Text>
                            )}
                          </Space>
                        </List.Item>
                      )
                    }}
                  />
                )}
                <Row gutter={[12, 12]}>
                  <Col xs={24} md={12}>
                    <List
                      size="small"
                      header="任务队列"
                      bordered
                      dataSource={runtime?.task_queue || []}
                      locale={{ emptyText: '暂无任务' }}
                      renderItem={(job) => (
                        <List.Item
                          actions={[
                            ...(job.agent === 'kernel'
                              ? [<Button key="trace" size="small" onClick={() => void watchKernelJob(String(job.id || ''))}>{['pending', 'running', 'cancelling'].includes(String(job.status || '')) ? '跟踪' : '回放'}</Button>]
                              : []),
                            ...(job.agent === 'kernel' && ['pending', 'running', 'cancelling'].includes(String(job.status || ''))
                              ? [<Button key="cancel" size="small" danger onClick={() => void cancelRuntimeJob(String(job.id || ''))}>取消</Button>]
                              : []),
                            ...(job.agent === 'kernel' && ['failed', 'cancelled'].includes(String(job.status || ''))
                              ? [<Button key="resume" size="small" loading={kernelLoading === String(job.id || '')} onClick={() => void runKernel(String(job.id || ''))}>{job.recoverable === true ? `从 step ${Number(job.checkpoint_step || 0)} 继续` : '重新运行'}</Button>]
                              : []),
                          ]}
                        >
                          <Space direction="vertical" size={2}>
                            <Space wrap>
                              <Tag>{String(job.agent || '-')}</Tag>
                              <Tag color={job.status === 'failed' ? 'red' : job.status === 'completed' ? 'green' : 'blue'}>{String(job.status || '-')}</Tag>
                              <Text type="secondary">{String(job.task || '')}</Text>
                              {job.recoverable === true && <Tag color="gold">checkpoint 已保存</Tag>}
                            </Space>
                            {Boolean(job.summary) && <Text>{String(job.summary)}</Text>}
                            {job.agent === 'kernel' && (job.status === 'completed' || kernelUsesRulesFallback(job)) && kernelActionsFromJob(job).length > 0 && (
                              <List
                                size="small"
                                dataSource={kernelActionsFromJob(job)}
                                header={kernelUsesRulesFallback(job)
                                  ? '规则降级建议（可先执行，也可稍后继续 Kernel）'
                                  : 'Kernel 建议（确认后才会写入任务）'}
                                renderItem={(action) => {
                                  const execution = kernelActionExecution(job, action.id)
                                  const loadingKey = `${String(job.id || '')}:${action.id}`
                                  return (
                                    <List.Item
                                      actions={[
                                        <Button
                                          key="prepare"
                                          size="small"
                                          type="link"
                                          disabled={Boolean(execution)}
                                          loading={kernelActionLoading === loadingKey}
                                          onClick={() => void openKernelActionDraft(String(job.id || ''), action)}
                                        >
                                          {execution ? (execution.status === 'created' ? '已创建任务' : '已确认') : '准备行动'}
                                        </Button>,
                                      ]}
                                    >
                                      <Space direction="vertical" size={0}>
                                        <Text>{action.title}</Text>
                                        <Text type="secondary">{action.reason}</Text>
                                      </Space>
                                    </List.Item>
                                  )
                                }}
                              />
                            )}
                          </Space>
                        </List.Item>
                      )}
                    />
                  </Col>
                  <Col xs={24} md={12}>
                    <List
                      size="small"
                      header="执行日志"
                      bordered
                      dataSource={runtime?.execution_logs || []}
                      locale={{ emptyText: '暂无日志' }}
                      renderItem={(log) => (
                        <List.Item>
                          <Space direction="vertical" size={2}>
                            <Space wrap>
                              <Tag>{String(log.agent || '-')}</Tag>
                              <Tag color={log.status === 'failed' ? 'red' : log.status === 'completed' ? 'green' : ['cancelled', 'interrupted'].includes(String(log.status || '')) ? 'orange' : 'blue'}>{String(log.status || '-')}</Tag>
                              <Text type="secondary">{String(log.created_at || '')}</Text>
                            </Space>
                            <Text>{String(log.message || '')}</Text>
                          </Space>
                        </List.Item>
                      )}
                    />
                  </Col>
                </Row>
              </Space>
            </Card>
          </>
        )}

        <Modal
          title="确认 Agent 行动草案"
          open={!!draft}
          onCancel={() => setDraft(null)}
          onOk={() => void confirmDraft()}
          confirmLoading={executeLoading}
          okText="确认创建"
          cancelText="取消"
        >
          {draft && (
            <Space direction="vertical" size={8} style={{ width: '100%' }}>
              <Alert type="info" showIcon message={draft.action.title} description={draft.action.reason} />
              <Card size="small">
                <Paragraph><Text strong>操作：</Text>{draft.draft.operation === 'create_task' ? '创建今日任务' : '跳转执行'}</Paragraph>
                {draft.draft.title && <Paragraph><Text strong>任务标题：</Text>{draft.draft.title}</Paragraph>}
                {draft.draft.description && <Paragraph><Text strong>说明：</Text>{draft.draft.description}</Paragraph>}
                {draft.draft.planned_date && <Paragraph><Text strong>计划日期：</Text>{draft.draft.planned_date}</Paragraph>}
                {draft.draft.estimated_minutes && <Paragraph><Text strong>预计时长：</Text>{draft.draft.estimated_minutes} 分钟</Paragraph>}
              </Card>
              <Paragraph type="secondary">Agent 只会在你确认后写入任务；如果状态已变化，请先刷新感知。</Paragraph>
            </Space>
          )}
        </Modal>

        <Modal
          title="确认 AgentKernel 行动草案"
          open={!!kernelActionDraft}
          onCancel={() => setKernelActionDraft(null)}
          onOk={() => kernelActionDraft && void executePreparedKernelAction(kernelActionDraft)}
          confirmLoading={executeLoading}
          okText="确认创建"
          cancelText="取消"
        >
          {kernelActionDraft && (
            <Space direction="vertical" size={8} style={{ width: '100%' }}>
              <Alert
                type="info"
                showIcon
                message={kernelActionDraft.action.title}
                description={kernelActionDraft.action.reason}
              />
              <Card size="small">
                <Paragraph><Text strong>来源任务：</Text>{kernelActionDraft.job_id}</Paragraph>
                <Paragraph><Text strong>操作：</Text>创建今日任务</Paragraph>
                {kernelActionDraft.draft.goal_title && <Paragraph><Text strong>所属目标：</Text>{kernelActionDraft.draft.goal_title}</Paragraph>}
                {kernelActionDraft.draft.title && <Paragraph><Text strong>任务标题：</Text>{kernelActionDraft.draft.title}</Paragraph>}
                {kernelActionDraft.draft.description && <Paragraph><Text strong>说明：</Text>{kernelActionDraft.draft.description}</Paragraph>}
                {kernelActionDraft.draft.planned_date && <Paragraph><Text strong>计划日期：</Text>{kernelActionDraft.draft.planned_date}</Paragraph>}
                {kernelActionDraft.draft.estimated_minutes && <Paragraph><Text strong>预计时长：</Text>{kernelActionDraft.draft.estimated_minutes} 分钟</Paragraph>}
              </Card>
              <Paragraph type="secondary">确认凭据已持久化；重复点击不会重复创建任务。目标状态发生变化时，服务端会拒绝旧草案。</Paragraph>
            </Space>
          )}
        </Modal>
      </Space>
    </PageShell>
  )
}
