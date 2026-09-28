import { useEffect, useMemo, useState, type CSSProperties } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import {
  ArrowRight,
  ArrowUp,
  AtSign,
  BookOpenCheck,
  Check,
  CircleX,
  Compass,
  Lightbulb,
  Pencil,
  Play,
  RefreshCw,
  Sparkle,
  Target,
  Timer,
  X,
} from 'lucide-react'
import {
  Button,
  Cite,
  CountUp,
  Empty,
  IconButton,
  LinkButton,
  Notice,
  ProgressRing,
  Section,
  Skeleton,
  Stat,
  StatGrid,
  cx,
  toast,
} from '../../ui'
import { useAuthStore } from '../../stores/authStore'
import { executeAgentAction, recordAgentActionFeedback } from '../../services/agentApi'
import { recordCoachNudgeFeedback, startCoachNudgeAction, type CoachNudge } from '../../services/coachApi'
import { updateGoalTask } from '../../services/goalApi'
import { usePageChrome, useShell } from '../../app/shell/shellStore'
import { qk } from '../../app/queryClient'
import { routeWithCoachAttempt, safeInternalRoute } from '../../app/coachRoutes'
import { EvidencePanel } from './EvidencePanel'
import { useTodayData, type DraftCard, type QueueItem } from './useTodayData'
import s from './today.module.css'

const QUEUE_ICON: Record<QueueItem['kind'], JSX.Element> = {
  focus: <Timer />,
  task: <Target />,
  wrong: <CircleX />,
  review: <BookOpenCheck />,
}
const QUEUE_LABEL: Record<QueueItem['kind'], string> = { focus: '专注', task: '任务', wrong: '错题', review: '复习' }

function greeting(h: number) {
  if (h < 5) return '夜深了'
  if (h < 11) return '早上好'
  if (h < 14) return '中午好'
  if (h < 18) return '下午好'
  return '晚上好'
}

function daysUntil(deadline?: string | null): number | null {
  if (!deadline) return null
  const d = new Date(`${deadline}T00:00:00`)
  if (Number.isNaN(d.getTime())) return null
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  return Math.round((d.getTime() - today.getTime()) / 86_400_000)
}

/* ============================================================================
   Page
   ========================================================================== */
export function TodayPage() {
  const data = useTodayData()
  const [activeCite, setActiveCite] = useState<number | null>(null)
  const setAsideOpen = useShell(st => st.setAsideOpen)

  const openCite = (n: number) => {
    setActiveCite(n)
    setAsideOpen(true)
  }

  const aside = useMemo(
    () => (
      <EvidencePanel
        sources={data.sources}
        active={activeCite}
        onActive={setActiveCite}
        memories={data.memories}
        candidates={data.candidates.data ?? []}
      />
    ),
    [data.sources, activeCite, data.memories, data.candidates.data],
  )

  usePageChrome({
    title: '今天',
    aside,
    asideLabel: '证据',
    actions: (
      <IconButton label="刷新今天的建议" onClick={data.refetchAll}>
        <RefreshCw />
      </IconButton>
    ),
  })

  // Wide screens: open the evidence rail by default the first time.
  useEffect(() => {
    if (window.innerWidth >= 1440 && localStorage.getItem('mx_today_evidence_seen') !== '1') {
      localStorage.setItem('mx_today_evidence_seen', '1')
      setAsideOpen(true)
    }
  }, [setAsideOpen])

  if (data.error) {
    return (
      <div className={s.page}>
        <Greeting data={data} />
        <Notice
          tone="danger"
          title="今天的学习安排暂时没能加载"
          actions={
            <Button size="sm" variant="secondary" icon={<RefreshCw />} onClick={data.refetchAll}>
              重新加载
            </Button>
          }
        >
          本地学习服务没有返回数据。确认后端已启动后再试一次。
        </Notice>
      </div>
    )
  }

  return (
    <div className={s.page}>
      <Greeting data={data} />
      <NextAction data={data} activeCite={activeCite} onCite={openCite} />
      <div className={s.grid}>
        <div className={s.col}>
          <Queue data={data} />
          <Drafts data={data} onCite={openCite} />
        </div>
        <div className={s.col}>
          <Rhythm data={data} />
          <Mastery data={data} />
          <CoachNudge data={data} />
          <DailyQuote data={data} />
        </div>
      </div>
      <Composer data={data} />
    </div>
  )
}

type Data = ReturnType<typeof useTodayData>

/* ============================================================================
   Greeting
   ========================================================================== */
function Greeting({ data }: { data: Data }) {
  const navigate = useNavigate()
  const user = useAuthStore(st => st.user)
  const now = new Date()
  const week = '日一二三四五六'[now.getDay()]
  const goal = data.ctx.data?.active_goal
  const progress = goal?.progress
  const left = daysUntil(goal?.deadline)
  const pending = data.queue.filter(q => !q.done).length
  const pendingMinutes = data.plan.totalMinutes
  const doneToday = data.queue.filter(q => q.done).length
  const ratio = data.queue.length > 0 ? doneToday / data.queue.length : 0

  return (
    <header className={s.greet}>
      <div>
        <div className={s.date}>
          <span>
            {now.getMonth() + 1}月{now.getDate()}日 星期{week}
          </span>
          {left !== null && left >= 0 && (
            <>
              <i />
              <span>
                距目标截止 <span className="mx-num">{left}</span> 天
              </span>
            </>
          )}
        </div>
        <h1 className={s.hello}>
          {greeting(now.getHours())}，{user?.username ?? '同学'}
        </h1>
        {data.loading ? (
          <Skeleton width={260} height={14} style={{ marginTop: 12 }} />
        ) : pending > 0 ? (
          <p className={s.helloSub}>
            今天还剩 <b>{pending} 件事</b>
            {pendingMinutes > 0 && (
              <>
                ，先做下面这一组，大约 <b>{pendingMinutes} 分钟</b>
              </>
            )}
            。
          </p>
        ) : (
          <p className={s.helloSub}>今天的安排已经清空了。用几分钟写一段复盘，明天会接得更顺。</p>
        )}
      </div>
      {goal && (
        <button type="button" className={s.goalPill} onClick={() => navigate('/goals')}>
          <ProgressRing value={ratio} size={36} stroke={3} label={`今日安排完成 ${Math.round(ratio * 100)}%`}>
            <span className={s.goalPct}>{Math.round(ratio * 100)}</span>
          </ProgressRing>
          <span className={s.goalText}>
            <span className={s.goalTitle}>{goal.title}</span>
            <span className={s.goalMeta}>
              待办 {progress?.pending_task_count ?? 0}
              {progress?.overdue_task_count ? ` · 逾期 ${progress.overdue_task_count}` : ''}
            </span>
          </span>
        </button>
      )}
    </header>
  )
}

/* ============================================================================
   Next action — the one thing
   ========================================================================== */
function NextAction({ data, activeCite, onCite }: { data: Data; activeCite: number | null; onCite: (n: number) => void }) {
  const navigate = useNavigate()
  const { plan } = data

  if (data.loading) {
    return (
      <section className={s.next} aria-busy="true" aria-label="下一步">
        <Skeleton width={90} height={12} />
        <Skeleton width="62%" height={24} style={{ margin: '14px 0 20px' }} />
        <div className={s.skelStack}>
          <Skeleton height={16} />
          <Skeleton height={16} width="86%" />
          <Skeleton height={16} width="74%" />
        </div>
      </section>
    )
  }

  const mission = plan.cta
  const primaryRoute = safeInternalRoute(plan.steps[0]?.route ?? mission?.route) ?? '/pomodoro'
  const primaryLabel = plan.steps[0]?.key === 'review' ? '开始复习' : mission?.cta || '开始专注'

  if (plan.steps.length === 0 && mission?.kind === 'setup') {
    return (
      <section className={s.next} aria-labelledby="next-title">
        <div className={s.nextHead}>
          <Compass aria-hidden />
          下一步
        </div>
        <h2 id="next-title" className={s.nextTitle}>
          {mission.title}
        </h2>
        <p className={s.helloSub} style={{ marginTop: -8, marginBottom: 18 }}>
          {mission.reason}
        </p>
        <div className={s.nextActions}>
          <Button variant="primary" onClick={() => navigate('/materials?upload=1')}>
            导入资料
          </Button>
          <Button variant="secondary" onClick={() => useShell.getState().setOnboardingOpen(true)}>
            用示例数据体验
          </Button>
        </div>
      </section>
    )
  }

  return (
    <section className={s.next} aria-labelledby="next-title">
      <div className={s.nextHead}>
        <Compass aria-hidden />
        下一步
        {plan.steps.length > 0 && (
          <span className={s.nextHeadMuted}>
            {plan.totalMinutes > 0 && (
              <>
                约 <span className="mx-num">{plan.totalMinutes}</span> 分钟 ·{' '}
              </>
            )}
            {plan.steps.length} 步
          </span>
        )}
      </div>
      <h2 id="next-title" className={s.nextTitle}>
        {plan.title}
      </h2>

      {plan.steps.length > 0 && (
        <ol className={s.steps}>
          {plan.steps.map((st, i) => (
            <li key={st.key} className={s.step}>
              <span className={s.stepIdx}>{i + 1}</span>
              <span className={s.stepText}>{st.label}</span>
              <span className={s.stepCites}>
                {st.cites.map(c => (
                  <Cite key={c} n={c} active={activeCite === c} onClick={() => onCite(c)} />
                ))}
              </span>
              <span className={s.stepMin}>{st.minutes ? `${st.minutes} 分钟` : ''}</span>
            </li>
          ))}
        </ol>
      )}

      {plan.reason && (
        <div className={s.reason}>
          <span className={s.reasonLabel}>为什么</span>
          <span>
            {plan.reason}{' '}
            {plan.reasonCites.map(c => (
              <Cite key={c} n={c} active={activeCite === c} onClick={() => onCite(c)} />
            ))}
          </span>
        </div>
      )}

      {plan.recall && (
        <p className={s.recall}>
          <strong>开始前先想一想</strong>
          {plan.recall}
        </p>
      )}

      <div className={s.nextActions}>
        <Button variant="primary" icon={<Play />} onClick={() => navigate(primaryRoute)}>
          {primaryLabel}
        </Button>
        <Button variant="secondary" icon={<Timer />} onClick={() => navigate(`/pomodoro?quick=${Math.min(45, Math.max(15, plan.totalMinutes || 25))}`)}>
          专注 {Math.min(45, Math.max(15, plan.totalMinutes || 25))} 分钟
        </Button>
        <span className={s.spacer} />
        <Button variant="ghost" size="sm" icon={<Pencil />} onClick={() => navigate('/plans')}>
          调整计划
        </Button>
      </div>
    </section>
  )
}

/* ============================================================================
   Queue — today's timeline
   ========================================================================== */
function Queue({ data }: { data: Data }) {
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [pending, setPending] = useState<Record<string, boolean>>({})
  const items = data.queue
  const nowKey = items.find(q => !q.done)?.key
  const left = items.filter(q => !q.done).length

  const complete = async (item: QueueItem) => {
    if (!item.taskId) return
    setPending(p => ({ ...p, [item.key]: true }))
    try {
      await updateGoalTask(item.taskId, { status: 'completed' })
      toast.success('完成一项', {
        description: item.title,
        actions: [
          {
            label: '撤销',
            onClick: () => {
              void updateGoalTask(item.taskId!, { status: 'pending' }).then(() => {
                void qc.invalidateQueries({ queryKey: qk.dailyTasks(data.today) })
                void qc.invalidateQueries({ queryKey: qk.dashboard })
              })
            },
          },
        ],
      })
      await Promise.all([
        qc.invalidateQueries({ queryKey: qk.dailyTasks(data.today) }),
        qc.invalidateQueries({ queryKey: qk.dashboard }),
        qc.invalidateQueries({ queryKey: qk.goalContext() }),
      ])
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '更新任务失败')
    } finally {
      setPending(p => ({ ...p, [item.key]: false }))
    }
  }

  return (
    <Section
      title="今日安排"
      meta={items.length > 0 ? `${items.length - left} / ${items.length} 已完成` : undefined}
      aside={<LinkButton onClick={() => navigate(`/plans?date=${data.today}`)}>查看计划</LinkButton>}
    >
      {data.tasks.isLoading || data.reviews.isLoading ? (
        <div className={s.skelStack}>
          {[0, 1, 2].map(i => (
            <Skeleton key={i} height={46} radius={10} />
          ))}
        </div>
      ) : items.length === 0 ? (
        <Empty
          align="start"
          icon={<Target />}
          title="今天还没有安排"
          body="从目标里挑一个任务，或者让教练根据资料生成今天的计划。"
          actions={
            <>
              <Button size="sm" variant="secondary" onClick={() => navigate(`/plans?date=${data.today}`)}>
                安排今天的学习
              </Button>
              <Button size="sm" variant="ghost" onClick={() => navigate('/goals')}>
                打开目标
              </Button>
            </>
          }
        />
      ) : (
        <ul className={s.queue}>
          {items.map(q => {
            const isNow = q.key === nowKey
            return (
              <li key={q.key} className={s.qItem} data-done={q.done || undefined} data-now={isNow || undefined}>
                <span className={s.qTime} aria-hidden>
                  {q.done ? '完成' : isNow ? '现在' : ''}
                </span>
                {q.taskId && !q.done ? (
                  <button
                    type="button"
                    className={s.qDot}
                    data-now={isNow || undefined}
                    aria-label={`标记完成：${q.title}`}
                    disabled={pending[q.key]}
                    onClick={() => void complete(q)}
                  >
                    {isNow ? QUEUE_ICON[q.kind] : <Check />}
                  </button>
                ) : (
                  <span className={s.qDot} aria-hidden>
                    {q.done ? <Check /> : QUEUE_ICON[q.kind]}
                  </span>
                )}
                <span className={s.qBody}>
                  <span className={s.qTitle}>{q.title}</span>
                  <span className={s.qDetail}>
                    <span className={s.qKind} data-tone={q.tone}>
                      {QUEUE_LABEL[q.kind]}
                    </span>
                    {q.detail && (
                      <>
                        ·<span className="mx-truncate">{q.detail}</span>
                      </>
                    )}
                  </span>
                </span>
                <span className={s.qGo}>
                  {!q.done &&
                    (isNow ? (
                      <Button size="sm" variant="secondary" iconRight={<ArrowRight />} onClick={() => navigate(q.route)}>
                        开始
                      </Button>
                    ) : (
                      <IconButton label={`打开：${q.title}`} size="sm" onClick={() => navigate(q.route)}>
                        <ArrowRight />
                      </IconButton>
                    ))}
                </span>
              </li>
            )
          })}
        </ul>
      )}
    </Section>
  )
}

/* ============================================================================
   Drafts — coach proposals that write nothing until confirmed
   ========================================================================== */
function Drafts({ data, onCite }: { data: Data; onCite: (n: number) => void }) {
  const qc = useQueryClient()
  const [state, setState] = useState<Record<string, 'busy' | 'committed' | 'gone'>>({})
  const visible = data.draftCards.filter(d => state[d.id] !== 'gone')

  const confirm = async (d: DraftCard) => {
    setState(p => ({ ...p, [d.id]: 'busy' }))
    const res = await executeAgentAction(d.actionId)
    if (!res) {
      setState(p => {
        const n = { ...p }
        delete n[d.id]
        return n
      })
      toast.error('写入没有成功', { description: '建议可能已经变化，刷新后再试一次。' })
      return
    }
    setState(p => ({ ...p, [d.id]: 'committed' }))
    void recordAgentActionFeedback(d.actionId, { outcome: 'accepted' })
    void qc.invalidateQueries({ queryKey: qk.dailyTasks(data.today) })
    void qc.invalidateQueries({ queryKey: qk.goalContext() })
  }

  const dismiss = (d: DraftCard) => {
    setState(p => ({ ...p, [d.id]: 'gone' }))
    void recordAgentActionFeedback(d.actionId, { outcome: 'dismissed' })
  }

  if (!data.draftsLoading && data.draftCards.length === 0) return null

  return (
    <Section title="待你确认" meta="教练的建议，确认后才会写入">
      <div className={s.drafts}>
        {data.draftsLoading && data.draftCards.length === 0 && <Skeleton height={118} radius={12} />}
        {!data.draftsLoading && visible.length === 0 && (
          <p className={s.helloSub} style={{ margin: 0, fontSize: 'var(--mx-type-meta)' }}>
            都处理完了。新的建议会出现在这里。
          </p>
        )}
        {visible.map(d => {
          const st = state[d.id]
          return (
            <article key={d.id} className={s.draft} data-state={st}>
              <div className={s.draftTop}>
                <span className={s.draftKind}>{st === 'committed' ? `已写入${d.kind}` : `${d.kind}草案`}</span>
                <span className={s.draftFrom}>来自今天的分析</span>
                {d.cites.length > 0 && (
                  <span className={s.draftCites}>
                    {d.cites.map(c => (
                      <Cite key={c} n={c} onClick={() => onCite(c)} />
                    ))}
                  </span>
                )}
              </div>
              <h4 className={s.draftTitle}>{d.title}</h4>
              <p className={s.draftBody}>{d.body}</p>
              <div className={s.draftActions}>
                {st === 'committed' ? (
                  <span className={s.stamp}>
                    <Check aria-hidden />
                    已确认
                  </span>
                ) : (
                  <>
                    <Button size="sm" variant="primary" icon={<Check />} loading={st === 'busy'} onClick={() => void confirm(d)}>
                      确认写入
                    </Button>
                    <span className={s.spacer} />
                    <IconButton label="不需要" size="sm" disabled={st === 'busy'} onClick={() => dismiss(d)}>
                      <X />
                    </IconButton>
                  </>
                )}
              </div>
            </article>
          )
        })}
      </div>
    </Section>
  )
}

/* ============================================================================
   Rhythm — quiet inline stats + a 7-day strip
   ========================================================================== */
function Rhythm({ data }: { data: Data }) {
  const navigate = useNavigate()
  const d = data.dashboard.data
  const days = data.week.data ?? []
  const max = Math.max(1, ...days.map(x => x.total_minutes))
  const activeDays = days.filter(x => x.total_minutes > 0).length
  const weekMinutes = days.reduce((a, b) => a + b.total_minutes, 0)
  return (
    <Section title="今天的节奏" aside={<LinkButton onClick={() => navigate('/eda')}>学习报告</LinkButton>}>
      <div className={s.stats}>
        <StatGrid cols={3}>
          <Stat label="今日专注" value={d ? <CountUp value={d.today_study_minutes} /> : '–'} unit="分钟" foot={`${d?.today_pomodoro_count ?? 0} 个番茄`} />
          <Stat label="待复习" value={d ? <CountUp value={d.due_review_count} /> : '–'} unit="项" foot={d && d.due_review_count > 0 ? '先做主动回忆' : '已清空'} />
          <Stat label="本周学习" value={<CountUp value={activeDays} />} unit="/ 7 天" foot={`${Math.round(weekMinutes)} 分钟`} />
        </StatGrid>
        {days.length > 0 && (
          <div className={s.week} role="img" aria-label={`近 7 天专注分钟：${days.map(x => Math.round(x.total_minutes)).join('、')}`}>
            {days.map((x, i) => (
              <span
                key={x.date}
                className={s.weekBar}
                data-on={x.total_minutes > 0 || undefined}
                data-today={i === days.length - 1 && x.total_minutes > 0 ? true : undefined}
                title={`${x.date.slice(5)} · ${Math.round(x.total_minutes)} 分钟`}
                style={{ height: `${Math.max(8, (x.total_minutes / max) * 100)}%`, '--i': i } as CSSProperties}
              />
            ))}
          </div>
        )}
      </div>
    </Section>
  )
}

/* ============================================================================
   Mastery — chapter bars from the mastery map
   ========================================================================== */
function Mastery({ data }: { data: Data }) {
  const navigate = useNavigate()
  const map = data.mastery.data
  const material = map?.materials?.[0]
  const weakest = new Set((map?.weak_points ?? []).map(w => w.chapter_title))
  if (data.mastery.isLoading) return <Skeleton height={140} radius={12} />
  if (!material) return null
  const level = (v: number) => (v >= 85 ? 5 : v >= 70 ? 4 : v >= 55 ? 3 : v >= 35 ? 2 : 1)
  return (
    <Section title="掌握度" aside={<LinkButton onClick={() => navigate('/mastery')}>全部</LinkButton>}>
      <div className={s.mastery}>
        <div className={s.mMaterial} title={material.material_title}>
          {material.material_title} · 平均 {Math.round(material.average_mastery)}%
        </div>
        {material.chapters.slice(0, 6).map((c, i) => (
          <div key={c.chapter_id} className={s.mRow} data-weak={weakest.has(c.chapter_title) || undefined}>
            <span className={s.mName} title={c.chapter_title}>
              {c.chapter_title}
            </span>
            <span className={s.mTrack} role="img" aria-label={`${c.chapter_title} 掌握度 ${Math.round(c.mastery_level)}%`}>
              <span
                className={s.mFill}
                style={{ width: `${Math.max(4, c.mastery_level)}%`, '--m-color': `var(--mx-m${level(c.mastery_level)})`, '--i': i } as CSSProperties}
              />
            </span>
            <span className={s.mPct}>{Math.round(c.mastery_level)}%</span>
          </div>
        ))}
        <div className={s.legend} aria-hidden>
          薄弱
          {[1, 2, 3, 4, 5].map(l => (
            <span key={l} style={{ background: `var(--mx-m${l})` }} />
          ))}
          牢固
        </div>
      </div>
    </Section>
  )
}

/* ============================================================================
   Coach nudge — one inline suggestion, never a notification pile
   ========================================================================== */
function CoachNudge({ data }: { data: Data }) {
  const navigate = useNavigate()
  const qc = useQueryClient()
  const nudge = (data.nudges.data ?? []).find(n => ['pending', 'shown'].includes(n.status)) as CoachNudge | undefined
  const [hidden, setHidden] = useState(false)
  if (!nudge || hidden) return null
  const route = safeInternalRoute(nudge.route || nudge.suggested_action?.route)
  const start = async () => {
    const started = await startCoachNudgeAction(nudge.id)
    if (!started) {
      toast.error('暂时无法开始这条建议')
      return
    }
    void qc.invalidateQueries({ queryKey: qk.coachNudges })
    if (route) navigate(routeWithCoachAttempt(route, started.attempt, nudge.id))
  }
  const later = async () => {
    setHidden(true)
    await recordCoachNudgeFeedback(nudge.id, { outcome: 'later' })
    void qc.invalidateQueries({ queryKey: qk.coachNudges })
  }
  return (
    <Section title="教练想提醒你">
      <div className={s.nudge}>
        <span className={s.nudgeIcon} aria-hidden>
          <Lightbulb />
        </span>
        <div className={s.nudgeBody}>
          <p className={s.nudgeTitle}>{nudge.title}</p>
          <p className={s.nudgeText}>{nudge.body}</p>
          <div className={s.nudgeActions}>
            {route && (
              <Button size="sm" variant="soft" onClick={() => void start()}>
                {nudge.suggested_action?.label || '去处理'}
              </Button>
            )}
            <Button size="sm" variant="ghost" onClick={() => void later()}>
              稍后
            </Button>
          </div>
        </div>
      </div>
    </Section>
  )
}

/* ============================================================================
   Quote — a single line, in the serif voice
   ========================================================================== */
function DailyQuote({ data }: { data: Data }) {
  const q = data.quote.data
  if (!q?.content) return null
  return (
    <blockquote className={s.quote}>
      {q.content}
      {q.author && <cite>— {q.author}</cite>}
    </blockquote>
  )
}

/* ============================================================================
   Composer — ask the coach with today's context attached
   ========================================================================== */
function Composer({ data }: { data: Data }) {
  const navigate = useNavigate()
  const [text, setText] = useState('')
  const [withCtx, setWithCtx] = useState(true)
  const focusStep = data.plan.steps[0]
  const ctxLabel = focusStep?.label
  const send = () => {
    const q = text.trim()
    if (!q) return
    const params = new URLSearchParams({ ask: q })
    if (withCtx && ctxLabel) params.set('context', ctxLabel)
    navigate(`/?${params.toString()}`)
  }
  return (
    <div className={s.composerDock}>
      <div className={s.composer}>
        {withCtx && ctxLabel && (
          <div className={s.composerCtx}>
            <span className={s.ctxChip}>
              <AtSign aria-hidden />
              <span>{ctxLabel}</span>
              <button type="button" aria-label="移除上下文" onClick={() => setWithCtx(false)}>
                <X />
              </button>
            </span>
            <span className={s.ctxHint}>已自动带上当前任务</span>
          </div>
        )}
        <textarea
          className={s.textarea}
          rows={1}
          aria-label="问教练"
          placeholder={ctxLabel ? `问教练：关于「${ctxLabel.slice(0, 16)}」，我哪里还没想清楚？` : '问教练一个问题…'}
          value={text}
          onChange={e => setText(e.target.value)}
          onKeyDown={e => {
            if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault()
              send()
            }
          }}
        />
        <div className={s.composerBar}>
          <button type="button" className={s.mode} onClick={() => navigate('/')}>
            <Sparkle aria-hidden />
            教练模式
          </button>
          <span className={s.spacer} />
          <button type="button" className={cx(s.send)} disabled={!text.trim()} aria-label="发送" onClick={send}>
            <ArrowUp />
          </button>
        </div>
      </div>
      <div className={s.composerFoot}>回答会标注来源；涉及写入的操作会先生成草案，由你确认。</div>
    </div>
  )
}
