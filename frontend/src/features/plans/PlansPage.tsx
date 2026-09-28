import { Suspense, lazy, useEffect, useMemo, useRef, useState, type CSSProperties } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  CalendarDays,
  CalendarPlus,
  Check,
  ChevronLeft,
  ChevronRight,
  Lightbulb,
  ListPlus,
  MessageSquareText,
  NotebookPen,
  Plus,
  ScanEye,
  Sparkles,
  Undo2,
} from 'lucide-react'
import { Button, Confirm, Empty, IconButton, Notice, ProgressBar, Skeleton, toast } from '../../ui'
import { listPlans, type PlanItem } from '../../services/planApi'
import { generateDailyPlan } from '../../services/learningApi'
import { generateFeynmanProbe, type FeynmanProbeResult } from '../../services/feynmanProbeApi'
import { confirmCoachNudgeDraft, getCoachNudgeDraft } from '../../services/coachApi'
import { getApiErrorMessage } from '../../services/apiClient'
import { usePageChrome } from '../../app/shell/shellStore'
import { localDay } from '../../lib/dates'
import type { MarkdownLiveEditorHandle } from '../../components/MarkdownLiveEditor'
import {
  appendTasks,
  checklistOf,
  dayTitle,
  isPlainDay,
  monthGrid,
  monthRange,
  previewOf,
  shiftMonth,
  statsOf,
  toggleLine,
} from './planModel'
import { usePlanDoc } from './usePlanDoc'
import s from './plans.module.css'

const MarkdownLiveEditor = lazy(() => import('../../components/MarkdownLiveEditor').then(m => ({ default: m.MarkdownLiveEditor })))

const WEEK = ['一', '二', '三', '四', '五', '六', '日']

export function PlansPage() {
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [params, setParams] = useSearchParams()
  const today = localDay()
  const day = isPlainDay(params.get('date')) ? params.get('date')! : today
  const [month, setMonth] = useState(day.slice(0, 7))
  const [railOpen, setRailOpen] = useState(false)
  const [generating, setGenerating] = useState(false)
  const [probing, setProbing] = useState(false)
  const [probe, setProbe] = useState<FeynmanProbeResult | null>(null)
  const [newTask, setNewTask] = useState('')
  const [confirmRegen, setConfirmRegen] = useState(false)
  const editorRef = useRef<MarkdownLiveEditorHandle | null>(null)

  // Keep the visible month on the selected day.
  useEffect(() => setMonth(day.slice(0, 7)), [day])
  useEffect(() => setProbe(null), [day])

  const range = monthRange(month)
  const rangeKey = useMemo(() => ['plans', range.start, range.end] as const, [range.start, range.end])
  const plans = useQuery({ queryKey: rangeKey, queryFn: () => listPlans(range.start, range.end), staleTime: 30_000 })
  // The selected day may be outside the visible month (e.g. deep link); fetch it on its own.
  const dayInRange = day >= range.start && day <= range.end
  const single = useQuery({
    queryKey: ['plans', day, day],
    queryFn: () => listPlans(day, day),
    enabled: !dayInRange,
    staleTime: 30_000,
  })
  const planByDay = useMemo(() => new Map((plans.data ?? []).map(p => [p.date, p])), [plans.data])
  const serverPlan = dayInRange ? planByDay.get(day) : single.data?.[0]
  const loadingDoc = dayInRange ? plans.isLoading : single.isLoading
  const doc = usePlanDoc(day, loadingDoc ? undefined : serverPlan?.content ?? '', dayInRange ? rangeKey : ['plans', day, day])

  const stats = statsOf(doc.content)
  const tasks = useMemo(() => checklistOf(doc.content), [doc.content])
  const title = dayTitle(day, today)

  const coachAttempt = params.get('coach_attempt')?.trim() || null
  const coachNudge = params.get('coach_nudge')?.trim() || null
  const draft = useQuery({
    queryKey: ['coach', 'nudge-draft', coachNudge],
    queryFn: () => getCoachNudgeDraft(coachNudge!),
    enabled: Boolean(coachNudge && coachAttempt),
  })
  const [confirming, setConfirming] = useState(false)

  usePageChrome({ title: '学习计划', bare: true })

  const go = (next: string) => {
    void doc.flush()
    const p = new URLSearchParams(params)
    p.set('date', next)
    p.delete('coach_attempt')
    p.delete('coach_nudge')
    setParams(p)
    setRailOpen(false)
  }

  const requestGenerate = () => {
    if (doc.content.trim()) setConfirmRegen(true)
    else void generate()
  }

  const generate = async () => {
    setGenerating(true)
    try {
      await doc.flush()
      const r = await generateDailyPlan(day)
      doc.replaceFromServer(r.content || '')
      void qc.invalidateQueries({ queryKey: ['plans'] })
      toast.success(`已生成 ${r.item_count} 项计划`, { description: '根据你的目标、到期复习和最近的学习情况。' })
    } catch (error) {
      toast.error(getApiErrorMessage(error, '生成计划失败'))
    } finally {
      setGenerating(false)
    }
  }

  const runProbe = async () => {
    if (doc.content.trim().length < 12) {
      toast.warning('先写几句今天的复盘', { description: '用自己的话讲讲今天学懂了什么，小白才能追问。' })
      return
    }
    setProbing(true)
    try {
      const r = await generateFeynmanProbe(day, doc.content, 4)
      if (!r) throw new Error('追问没有生成')
      setProbe(r)
    } catch (error) {
      toast.error(getApiErrorMessage(error, '追问生成失败，请稍后重试'))
    } finally {
      setProbing(false)
    }
  }

  const appendProbe = () => {
    if (!probe) return
    const block = [
      '',
      '---',
      '',
      `## ${probe.name}`,
      `> ${probe.tagline}`,
      '',
      `**讲得清楚的地方：** ${probe.strongest_part}`,
      '',
      '**小白会追问：**',
      ...probe.questions.map((q, i) => `${i + 1}. **${q.type}**：${q.question}`),
      '',
      `- [ ] ${probe.next_focus}`,
      '',
    ].join('\n')
    doc.setContent(prev => `${prev.trimEnd()}\n${block}`)
    editorRef.current?.setMarkdown(`${doc.content.trimEnd()}\n${block}`)
    toast.success('已追加到今天的计划', { description: '最后一条变成了明天要补的任务。' })
  }

  const toggle = (line: number) => {
    const next = toggleLine(doc.content, line)
    doc.setContent(next)
    editorRef.current?.setMarkdown(next)
  }

  const addTask = () => {
    const t = newTask.trim()
    if (!t) return
    const next = appendTasks(doc.content, [t])
    doc.setContent(next)
    editorRef.current?.setMarkdown(next)
    setNewTask('')
  }

  const confirmDraft = async () => {
    if (!coachNudge || !coachAttempt) return
    setConfirming(true)
    try {
      const r = await confirmCoachNudgeDraft(coachNudge, coachAttempt)
      if (!r) throw new Error('草案确认失败，请刷新后重试')
      toast.success(r.result.message || '已加入计划')
      const planDate = String(r.result.created?.plan?.date || draft.data?.draft.date || day)
      void qc.invalidateQueries({ queryKey: ['plans'] })
      go(isPlainDay(planDate) ? planDate : day)
    } catch (error) {
      toast.error(getApiErrorMessage(error, '确认失败'))
    } finally {
      setConfirming(false)
    }
  }

  return (
    <div className={s.root} data-rail={railOpen ? 'open' : undefined}>
      <PlanRail
        month={month}
        onMonth={setMonth}
        day={day}
        today={today}
        planByDay={planByDay}
        loading={plans.isLoading}
        onPick={go}
      />

      <section className={s.doc} aria-label="当天计划">
        <div className={s.docBar}>
          <span className="mx-show-compact">
            <IconButton label="选择日期" onClick={() => setRailOpen(true)}>
              <CalendarDays />
            </IconButton>
          </span>
          <IconButton label="前一天" size="sm" onClick={() => go(localDay(new Date(Date.parse(`${day}T00:00:00`) - 86_400_000)))}>
            <ChevronLeft />
          </IconButton>
          <IconButton label="后一天" size="sm" onClick={() => go(localDay(new Date(Date.parse(`${day}T00:00:00`) + 86_400_000)))}>
            <ChevronRight />
          </IconButton>
          {day !== today && (
            <Button size="sm" variant="ghost" icon={<Undo2 />} onClick={() => go(today)}>
              回到今天
            </Button>
          )}
          <span className={s.spacer} />
          <SaveIndicator state={doc.state} error={doc.error} onRetry={() => void doc.flush()} />
        </div>

        <div className={s.docScroll}>
          <div className={s.page}>
            {(draft.data || draft.isLoading) && (
              <Notice
                tone="ink"
                icon={<Sparkles />}
                className={s.draft}
                title={draft.data?.nudge.title || '教练准备了一份计划草案'}
                actions={
                  draft.data && (
                    <Button size="sm" variant="primary" loading={confirming} onClick={() => void confirmDraft()}>
                      确认加入
                    </Button>
                  )
                }
              >
                {draft.data
                  ? `将加入：${(draft.data.draft.items ?? []).map(i => i.title).filter(Boolean).join('；') || '一个最小学习计划'}。确认之前不会写入。`
                  : '正在读取草案…'}
              </Notice>
            )}

            <header className={s.dateHead} key={day}>
              <h1 className={s.datePrimary}>{title.primary}</h1>
              <span className={s.dateSecondary}>{title.secondary}</span>
            </header>

            <div className={s.dateActions}>
              <Button variant={stats.total === 0 ? 'primary' : 'secondary'} icon={<Sparkles />} loading={generating} onClick={requestGenerate}>
                {stats.total === 0 ? 'AI 排这一天' : '重新生成'}
              </Button>
              <Button variant="ghost" icon={<ScanEye />} loading={probing} onClick={() => void runProbe()}>
                明镜追问
              </Button>
              <Button variant="ghost" icon={<MessageSquareText />} onClick={() => navigate(`/?${new URLSearchParams({ ask: '帮我看看这一天的计划排得合不合理，太满的话帮我砍到最小可完成版本。', context: `${title.primary}的学习计划` })}`)}>
                问教练
              </Button>
            </div>

            {loadingDoc ? (
              <div className={s.skel} aria-busy="true" aria-label="正在加载计划">
                <Skeleton height={120} radius={12} />
                <Skeleton height={16} width="70%" />
                <Skeleton height={16} width="55%" />
              </div>
            ) : (
              <>
                <section className={s.checklist} aria-labelledby="checklist-title">
                  <div className={s.checkHead}>
                    <h2 id="checklist-title" className={s.checkTitle}>
                      要做的事
                    </h2>
                    <span className={s.checkCount}>
                      {stats.done} / {stats.total}
                    </span>
                    {stats.total > 0 && <ProgressBar className={s.checkBar} value={stats.ratio} label="完成度" color="var(--mx-success)" />}
                  </div>
                  {tasks.length === 0 ? (
                    <Empty
                      align="start"
                      icon={<ListPlus />}
                      title="这一天还没有任务"
                      body="让 AI 按你的目标和到期复习排一版，或者在下面直接写。"
                    />
                  ) : (
                    <ul className={s.tasks}>
                      {tasks.map(t => (
                        <li key={t.line}>
                          <button type="button" className={s.task} aria-pressed={t.done} onClick={() => toggle(t.line)}>
                            <span className={s.box} aria-hidden>
                              <Check />
                            </span>
                            <span className={s.taskText}>{t.title}</span>
                          </button>
                        </li>
                      ))}
                    </ul>
                  )}
                  <form
                    className={s.addRow}
                    onSubmit={e => {
                      e.preventDefault()
                      addTask()
                    }}
                  >
                    <input
                      className={s.addInput}
                      value={newTask}
                      placeholder="加一件事，回车确认"
                      aria-label="新任务"
                      onChange={e => setNewTask(e.target.value)}
                    />
                    {newTask.trim() && (
                      <IconButton label="添加" size="sm" type="submit">
                        <Plus />
                      </IconButton>
                    )}
                  </form>
                </section>

                <p className={s.editorLabel}>
                  <NotebookPen style={{ width: 14, height: 14 }} aria-hidden />
                  计划与复盘
                </p>
                <div className="mx-md">
                  <Suspense fallback={<Skeleton height={240} radius={10} />}>
                    <MarkdownLiveEditor
                      key={day}
                      ref={editorRef}
                      value={doc.content}
                      onChange={doc.setContent}
                      height="auto"
                      placeholder={'写下今天的安排，或学完后用自己的话复盘：今天真正弄懂了什么？'}
                    />
                  </Suspense>
                </div>

                {probe && <ProbePanel probe={probe} onAppend={appendProbe} onDismiss={() => setProbe(null)} />}
              </>
            )}
          </div>
        </div>
      </section>
      <Confirm
        open={confirmRegen}
        onOpenChange={setConfirmRegen}
        title="重新生成这一天的计划？"
        description="AI 会按你现在的目标和复习情况重新排一版，替换当前内容。已勾选的进度不会保留。"
        confirmLabel="重新生成"
        onConfirm={generate}
      />
    </div>
  )
}

function SaveIndicator({ state, error, onRetry }: { state: string; error: string | null; onRetry: () => void }) {
  const text = state === 'saving' ? '正在保存' : state === 'dirty' ? '有改动' : state === 'error' ? error || '保存失败' : '已保存'
  return (
    <span className={s.save} data-state={state} role="status">
      <i aria-hidden />
      {text}
      {state === 'error' && (
        <Button size="sm" variant="ghost" onClick={onRetry}>
          重试
        </Button>
      )}
    </span>
  )
}

/* ============================================================================
   Rail — month calendar with per-day completion, and the month's plans
   ========================================================================== */
function PlanRail({
  month,
  onMonth,
  day,
  today,
  planByDay,
  loading,
  onPick,
}: {
  month: string
  onMonth: (m: string) => void
  day: string
  today: string
  planByDay: Map<string, PlanItem>
  loading: boolean
  onPick: (d: string) => void
}) {
  const grid = monthGrid(month, today)
  const [y, m] = month.split('-').map(Number)
  const inMonth = [...planByDay.values()]
    .filter(p => p.date.startsWith(month) && p.content.trim())
    .sort((a, b) => b.date.localeCompare(a.date))

  return (
    <aside className={s.rail} aria-label="计划日历">
      <div className={s.railScroll}>
        <div className={s.monthHead}>
          <h2 className={s.monthTitle}>
            {y}年{m}月
          </h2>
          <IconButton label="上个月" size="sm" onClick={() => onMonth(shiftMonth(month, -1))}>
            <ChevronLeft />
          </IconButton>
          <IconButton label="下个月" size="sm" onClick={() => onMonth(shiftMonth(month, 1))}>
            <ChevronRight />
          </IconButton>
        </div>
        <div className={s.weekdays} aria-hidden>
          {WEEK.map(w => (
            <span key={w}>{w}</span>
          ))}
        </div>
        <div className={s.grid} role="grid" aria-label={`${y}年${m}月`}>
          {grid.map(c => {
            const plan = planByDay.get(c.day)
            const st = plan ? statsOf(plan.content) : null
            const hasText = Boolean(plan?.content.trim())
            return (
              <button
                key={c.day}
                type="button"
                className={s.cell}
                data-out={!c.inMonth || undefined}
                data-today={c.isToday || undefined}
                aria-pressed={c.day === day}
                aria-label={`${c.day}${hasText ? (st && st.total ? `，完成 ${st.done}/${st.total}` : '，有计划') : ''}`}
                onClick={() => onPick(c.day)}
              >
                {Number(c.day.slice(8))}
                {hasText ? (
                  st && st.total > 0 ? (
                    <span className={s.mark} style={{ '--p': st.ratio } as CSSProperties}>
                      <i />
                    </span>
                  ) : (
                    <span className={s.mark} data-empty="true" />
                  )
                ) : (
                  <span className={s.markSpacer} />
                )}
              </button>
            )
          })}
        </div>

        <section className={s.railSection} aria-label="本月的计划">
          <h3 className={s.railTitle}>
            本月的计划 <span>{inMonth.length}</span>
          </h3>
          {loading ? (
            <div className={s.skel}>
              <Skeleton height={40} radius={9} />
              <Skeleton height={40} radius={9} />
            </div>
          ) : inMonth.length === 0 ? (
            <Empty
              align="start"
              icon={<CalendarPlus />}
              title="这个月还没有计划"
              body="点日历上的任意一天开始写，或者让 AI 帮你排。"
            />
          ) : (
            <ul className={s.days}>
              {inMonth.map(p => {
                const st = statsOf(p.content)
                const [, mm, dd] = p.date.split('-').map(Number)
                const dt = new Date(Date.parse(`${p.date}T00:00:00`))
                return (
                  <li key={p.date}>
                    <button type="button" className={s.day} aria-current={p.date === day || undefined} onClick={() => onPick(p.date)}>
                      <span className={s.dayDate}>
                        <b>
                          {mm}/{dd}
                        </b>
                        <span>{p.date === today ? '今天' : `周${'日一二三四五六'[dt.getDay()]}`}</span>
                      </span>
                      <span className={s.dayPreview}>{previewOf(p.content) || '空白计划'}</span>
                      {st.total > 0 && (
                        <span className={s.dayCount} data-done={st.done === st.total || undefined}>
                          {st.done}/{st.total}
                        </span>
                      )}
                    </button>
                  </li>
                )
              })}
            </ul>
          )}
        </section>
      </div>
    </aside>
  )
}

/* ============================================================================
   明镜追问 — a newcomer's questions about your own reflection
   ========================================================================== */
function ProbePanel({ probe, onAppend, onDismiss }: { probe: FeynmanProbeResult; onAppend: () => void; onDismiss: () => void }) {
  return (
    <section className={s.probe} aria-labelledby="probe-title" aria-live="polite">
      <div className={s.probeHead}>
        <Lightbulb aria-hidden />
        <h2 id="probe-title" className={s.probeName}>
          {probe.name}
        </h2>
      </div>
      <p className={s.probeTag}>
        {probe.tagline}
        {probe.fallback && '（AI 暂不可用，这是基础版追问）'}
      </p>
      <p className={s.strong}>
        <b>讲得清楚的地方：</b>
        {probe.strongest_part}
      </p>
      <ol className={s.questions}>
        {probe.questions.map((q, i) => (
          <li key={i} className={s.question}>
            <div>
              <span className={s.qType}>{q.type}</span>
              <p className={s.qText}>{q.question}</p>
              <p className={s.qWhy}>为什么问：{q.why}</p>
            </div>
          </li>
        ))}
      </ol>
      <p className={s.next}>
        <b>下一步最小补缺口：</b>
        {probe.next_focus}
      </p>
      <div className={s.probeActions}>
        <Button size="sm" variant="primary" onClick={onAppend}>
          追加到计划
        </Button>
        <Button size="sm" variant="ghost" onClick={onDismiss}>
          收起
        </Button>
      </div>
    </section>
  )
}

