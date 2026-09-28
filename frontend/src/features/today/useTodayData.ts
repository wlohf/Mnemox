import { useMemo } from 'react'
import { useQueries, useQuery } from '@tanstack/react-query'
import { getDashboard } from '../../services/learningApi'
import {
  getAgentActionDraft,
  getAgentBrief,
  getAgentCoreProfile,
  getAgentGoalContext,
  listAgentMemoryCandidates,
  type AgentAction,
  type AgentActionDraftResponse,
} from '../../services/agentApi'
import { getMasteryMap } from '../../services/learningApi'
import { getDailyStats } from '../../services/pomodoroApi'
import { getCurrentQuote } from '../../services/motivationApi'
import { listCoachNudges } from '../../services/coachApi'
import { listDailyTasks, type GoalTaskItem } from '../../services/goalApi'
import { listReviewTasks, type ReviewTaskItem } from '../../services/reviewApi'
import { qk } from '../../app/queryClient'
import { buildEvidence, citeFor, parseCoreProfile, type EvidenceSource } from './evidence'

export function localDay(d = new Date()): string {
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

export interface PlanStep {
  key: string
  label: string
  minutes?: number
  cites: number[]
  route?: string
}

export interface QueueItem {
  key: string
  kind: 'review' | 'task' | 'wrong' | 'focus'
  title: string
  detail: string
  done: boolean
  route: string
  taskId?: number
  tone?: 'evidence' | 'danger'
}

export interface DraftCard {
  id: string
  actionId: string
  kind: '任务' | '笔记' | '记忆'
  title: string
  body: string
  cites: number[]
  response: AgentActionDraftResponse
}

const TASK_KIND: Record<string, string> = {
  learn: '学习',
  summarize: '复盘',
  practice: '练习',
  review: '复习',
}

/** Actions whose draft writes something, shown as "待你确认". */
// Must match the action ids emitted by backend agent_service (write-type drafts).
const WRITE_ACTIONS = ['weakness_drill', 'reduce_distraction', 'make_today_minimum_plan', 'maintain_rhythm']

export function useTodayData() {
  const today = localDay()
  const dashboard = useQuery({ queryKey: qk.dashboard, queryFn: getDashboard })
  const ctx = useQuery({ queryKey: qk.goalContext(), queryFn: () => getAgentGoalContext() })
  const brief = useQuery({ queryKey: qk.brief(false), queryFn: () => getAgentBrief(false), staleTime: 60_000 })
  const tasks = useQuery({ queryKey: qk.dailyTasks(today), queryFn: () => listDailyTasks(today) })
  const reviews = useQuery({ queryKey: qk.reviewTasks('due', 'all'), queryFn: () => listReviewTasks('due', 'all') })
  const mastery = useQuery({ queryKey: qk.masteryMap, queryFn: getMasteryMap, staleTime: 5 * 60_000 })
  const week = useQuery({ queryKey: qk.pomodoroDaily(7), queryFn: () => getDailyStats(7), staleTime: 60_000 })
  const quote = useQuery({ queryKey: qk.motivation, queryFn: () => getCurrentQuote(), staleTime: 30 * 60_000 })
  const core = useQuery({ queryKey: qk.coreProfile, queryFn: getAgentCoreProfile, staleTime: 5 * 60_000 })
  const candidates = useQuery({ queryKey: qk.memoryCandidates, queryFn: listAgentMemoryCandidates, staleTime: 60_000 })
  const nudges = useQuery({ queryKey: qk.coachNudges, queryFn: () => listCoachNudges(undefined, 10), staleTime: 60_000 })

  const writeActions = useMemo(
    () => (brief.data?.next_actions ?? []).filter(a => WRITE_ACTIONS.includes(a.id)).slice(0, 2),
    [brief.data],
  )
  const drafts = useQueries({
    queries: writeActions.map(a => ({
      queryKey: ['agent', 'action-draft', a.id, brief.data?.generated_at],
      queryFn: () => getAgentActionDraft(a.id),
      staleTime: 5 * 60_000,
    })),
  })

  const sources: EvidenceSource[] = useMemo(
    () => buildEvidence(ctx.data, brief.data, core.data),
    [ctx.data, brief.data, core.data],
  )

  const plan = useMemo(() => buildPlan(dashboard.data, ctx.data, brief.data?.next_actions ?? [], reviews.data ?? [], sources), [
    dashboard.data,
    ctx.data,
    brief.data,
    reviews.data,
    sources,
  ])

  const queue: QueueItem[] = useMemo(() => buildQueue(tasks.data ?? [], reviews.data ?? []), [tasks.data, reviews.data])

  const draftCards: DraftCard[] = useMemo(() => {
    const out: DraftCard[] = []
    drafts.forEach((q, i) => {
      const res = q.data
      const action = writeActions[i]
      if (!res || !action || !res.requires_confirmation || res.draft.operation !== 'create_task') return
      out.push({
        id: `${action.id}:${res.draft.title}`,
        actionId: action.id,
        kind: '任务',
        title: res.draft.title || action.title,
        body: sentence([
          res.draft.description,
          res.draft.estimated_minutes ? `预计 ${res.draft.estimated_minutes} 分钟` : '',
          res.draft.planned_date ? `排在${monthDay(res.draft.planned_date)}` : '',
        ]),
        cites: citeFor(sources, [action.reason, ...(action.explainability?.data_signals ?? [])]),
        response: res,
      })
    })
    return out
  }, [drafts, writeActions, sources])

  const memories = useMemo(() => {
    const groups = parseCoreProfile(core.data)
    const label: Record<string, string> = { goal: '学习目标', style: '学习偏好', pattern: '行为规律' }
    return groups.flatMap(g => g.items.slice(0, 2).map(text => ({ text: text.replace(/^画像摘要：/, ''), meta: `${label[g.category] ?? g.category} · 已确认` })))
  }, [core.data])

  const loading = dashboard.isLoading || ctx.isLoading
  const error = dashboard.isError && ctx.isError

  return {
    today,
    dashboard,
    ctx,
    brief,
    tasks,
    reviews,
    mastery,
    week,
    quote,
    candidates,
    nudges,
    sources,
    plan,
    queue,
    draftCards,
    draftsLoading: drafts.some(d => d.isLoading),
    memories,
    loading,
    error,
    refetchAll: () => {
      void dashboard.refetch()
      void ctx.refetch()
      void brief.refetch()
      void tasks.refetch()
      void reviews.refetch()
    },
  }
}

/* ---------------------------------------------------------------------------
   Plan: the one thing to do next, as up to three concrete steps.
--------------------------------------------------------------------------- */
function buildPlan(
  dash: Awaited<ReturnType<typeof getDashboard>> | undefined,
  ctx: Awaited<ReturnType<typeof getAgentGoalContext>> | undefined,
  actions: AgentAction[],
  reviews: ReviewTaskItem[],
  sources: EvidenceSource[],
) {
  const mission = dash?.today_mission
  const focus = ctx?.today_focus
  const steps: PlanStep[] = []

  if (reviews.length > 0) {
    const q = reviews.filter(r => r.item_type === 'question').length
    steps.push({
      key: 'review',
      label: q ? `主动回忆 ${reviews.length} 项到期复习（含 ${q} 道题）` : `复习 ${reviews.length} 个到期章节`,
      minutes: reviews.length <= 1 ? 10 : 15,
      cites: citeFor(sources, ['复习 到期']),
      route: '/review',
    })
  }
  const drill = actions.find(a => a.id === 'weakness_drill')
  if (drill) {
    steps.push({
      key: 'drill',
      label: drill.title.replace(/^针对薄弱点专项练习：/, '专项补缺：'),
      minutes: drill.estimated_minutes,
      cites: citeFor(sources, [drill.reason, ...(drill.explainability?.data_signals ?? [])]),
      route: drill.route,
    })
  }
  if (focus && !steps.some(st => st.label.includes(focus.title))) {
    steps.push({
      key: 'focus',
      label: focus.title,
      minutes: focus.estimated_minutes,
      cites: citeFor(sources, [focus.reason, '专注 番茄']),
      route: focus.route,
    })
  }
  const pending = dash?.today_tasks.filter(t => t.status !== 'completed') ?? []
  if (steps.length < 3 && pending[0] && !steps.some(st => st.label === pending[0].title)) {
    steps.push({ key: `task-${pending[0].id}`, label: pending[0].title, minutes: 25, cites: citeFor(sources, ['笔记 复盘']), route: '/goals' })
  }

  const title = composeTitle(steps, mission?.title)
  const signals = Array.from(
    new Set(
      [drill, actions.find(a => a.id === 'reduce_distraction')]
        .flatMap(a => a?.explainability?.data_signals ?? [])
        .map(sig => sig.replace(/^错题薄弱点：/, '反复出错的「').replace(/^(反复出错的「.+)$/, '$1」')),
    ),
  )
  const base = (focus?.reason || mission?.reason || '').trim()
  const reason = signals.length ? `${base.replace(/[。.]$/, '')}。参考了${signals.join('、')}。` : base
  return {
    title,
    steps: steps.slice(0, 3),
    totalMinutes: steps.slice(0, 3).reduce((a, b) => a + (b.minutes ?? 0), 0),
    reason,
    reasonCites: citeFor(sources, [reason, '走神 专注', '错题']),
    recall: mission?.active_recall_prompt,
    cta: mission,
  }
}

function composeTitle(steps: PlanStep[], fallback?: string): string {
  const hasReview = steps[0]?.key === 'review'
  const drill = steps.find(s => s.key === 'drill')
  if (drill && hasReview) return `先清掉到期复习，再补稳「${drill.label.replace(/^专项补缺：/, '')}」`
  if (hasReview && steps.length > 1) return `先清掉到期复习，再推进「${steps[1].label}」`
  if (drill) return `今天先补稳「${drill.label.replace(/^专项补缺：/, '')}」`
  return fallback || steps[0]?.label || '今天从一个最小行动开始'
}

/** Join clauses into one Chinese sentence without doubled punctuation. */
export function sentence(parts: Array<string | undefined | null>): string {
  const clean = parts
    .map(p => (p ?? '').trim().replace(/[。．.，,；;]+$/u, ''))
    .filter(Boolean)
  return clean.length ? `${clean.join('，')}。` : ''
}

export function monthDay(iso: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso)
  return m ? `${Number(m[2])}月${Number(m[3])}日` : iso
}

/* ---------------------------------------------------------------------------
   Queue: today's tasks + due reviews, as one ordered list.
--------------------------------------------------------------------------- */
function buildQueue(tasks: GoalTaskItem[], reviews: ReviewTaskItem[]): QueueItem[] {
  const items: QueueItem[] = []
  if (reviews.length > 0) {
    const overdue = reviews.filter(r => r.next_review_at && new Date(`${r.next_review_at}Z`).getTime() < Date.now() - 86_400_000).length
    items.push({
      key: 'review',
      kind: 'review',
      title: `到期复习 · ${reviews[0].chapter_title || '复习队列'}`,
      detail: `${reviews.length} 项${overdue ? ` · ${overdue} 项逾期` : ''}`,
      done: false,
      route: '/review',
      tone: 'evidence',
    })
  }
  for (const t of tasks) {
    items.push({
      key: `task-${t.id}`,
      kind: t.task_type === 'review' ? 'review' : 'task',
      title: t.title,
      detail: [TASK_KIND[t.task_type ?? ''] ?? '任务', t.chapter_title].filter(Boolean).join(' · '),
      done: t.status === 'completed',
      route: '/goals',
      taskId: t.id,
    })
  }
  // Done items sink to the top of the timeline (morning → now).
  return [...items.filter(i => i.done), ...items.filter(i => !i.done)]
}
