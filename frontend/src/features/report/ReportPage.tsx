import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { useLocation, useNavigate, useSearchParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, ArrowRight, BookOpenCheck, Copy, Info, Lightbulb, RefreshCw, Sparkles, Table2 } from 'lucide-react'
import { Badge, Button, Empty, IconButton, Notice, Segmented, Skeleton, toast } from '../../ui'
import { getEdaReport, getNorthStarMetrics, type EDAReport, type NorthStarMetricsReport } from '../../services/analyticsApi'
import { generateDailyIntervention, getDailyIntervention } from '../../services/interventionApi'
import { getWeeklyLearningReport } from '../../services/agentApi'
import { getProfile } from '../../services/profileApi'
import { usePageChrome } from '../../app/shell/shellStore'
import { qk } from '../../app/queryClient'
import { safeInternalRoute } from '../../app/coachRoutes'
import { DataTable, HeatScale, HeatmapChart, LengthChart, OutcomeChart, TrendChart, type DayPoint } from './Charts'
import { ProfileSection } from './ProfileSection'
import { RISK_META, formatMinutes, heatGrid, outcomesOf, reportTarget, shortMD, timeCaption, trendCaption, windowHours, type Period } from './reportModel'
import s from './report.module.css'

const TZ = Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC'
const PERIODS: Period[] = [7, 30, 90]

export function ReportPage() {
  const navigate = useNavigate()
  const location = useLocation()
  const [params, setParams] = useSearchParams()
  const qc = useQueryClient()
  const period = (PERIODS.find(p => String(p) === params.get('days')) ?? 30) as Period
  const [tables, setTables] = useState(false)
  const target = reportTarget(location.search, location.hash)

  const eda = useQuery({ queryKey: ['analytics', 'eda', period], queryFn: () => getEdaReport(period), placeholderData: prev => prev, staleTime: 60_000 })
  const north = useQuery({ queryKey: ['analytics', 'north-star', TZ], queryFn: () => getNorthStarMetrics(28, TZ), staleTime: 5 * 60_000 })
  const weekly = useQuery({ queryKey: ['agent', 'weekly-report', TZ], queryFn: () => getWeeklyLearningReport(TZ), staleTime: 5 * 60_000 })
  const today = useQuery({ queryKey: qk.intervention, queryFn: () => getDailyIntervention(0), staleTime: 5 * 60_000 })
  const profile = useQuery({ queryKey: qk.profile, queryFn: getProfile, staleTime: 5 * 60_000 })
  const [generating, setGenerating] = useState(false)

  usePageChrome({
    title: '学习报告',
    actions: (
      <IconButton label={tables ? '显示图表' : '以表格查看数据'} active={tables} onClick={() => setTables(v => !v)}>
        <Table2 />
      </IconButton>
    ),
  })

  // Scroll only once every section above a deep-link target has its final
  // height, otherwise late data pushes the target back out of view.
  const settled = [eda, north, weekly, today, profile].every(q => !q.isLoading)
  const flash = useScrollToTarget(target, settled)
  const setPeriod = (p: Period) => {
    const next = new URLSearchParams(params)
    next.set('days', String(p))
    next.delete('tab')
    setParams(next, { replace: true })
  }

  const report = eda.data
  const days: DayPoint[] = useMemo(
    () =>
      (report?.charts?.daily_trend?.length ? report.charts.daily_trend : report?.daily_points ?? []).map(d => ({
        date: d.date,
        minutes: d.study_minutes ?? 0,
        mean: d.rolling7_minutes ?? 0,
        sessions: d.pomodoro_count,
      })),
    [report],
  )
  const grid = useMemo(() => (report ? heatGrid(report) : null), [report])
  const best = report?.summary.best_study_window ?? report?.profile?.best_study_window
  const bestHours = useMemo(() => windowHours(best), [best])
  const outcomes = useMemo(() => (report ? outcomesOf(report.summary) : []), [report])
  const lengths = (report?.charts?.duration_bucket_distribution ?? []).map(b => ({
    label: b.bucket.replace('<20m', '20 分钟内').replace('20-29m', '20–29 分钟').replace('30-44m', '30–44 分钟').replace('45m+', '45 分钟以上'),
    count: b.count,
  }))

  const regenerate = async () => {
    setGenerating(true)
    try {
      const r = await generateDailyIntervention()
      if (!r) throw new Error('没能生成')
      qc.setQueryData(qk.intervention, r)
      toast.success('已按现在的数据重新检查')
    } catch {
      toast.error('检查失败，请稍后重试')
    } finally {
      setGenerating(false)
    }
  }

  const copyMarkdown = async () => {
    if (!report?.markdown) return
    try {
      await navigator.clipboard.writeText(report.markdown)
      toast.success('报告全文已复制', { description: '可以粘贴到笔记或 Obsidian。' })
    } catch {
      toast.error('没能访问剪贴板，请检查浏览器权限')
    }
  }

  return (
    <div className={s.page}>
      <header className={s.head}>
        <div>
          <h1 className={s.title}>学习报告</h1>
          <p className={s.lead}>{weekly.data?.headline ?? '从你的专注、复习和任务记录里看学习节奏。数字都来自真实记录，不做推测。'}</p>
        </div>
        {report && (
          <span className={s.range}>
            {report.start_date} 至 {report.end_date}
          </span>
        )}
      </header>

      <div className={s.filters}>
        <Segmented
          ariaLabel="时间范围"
          value={String(period) as '7' | '30' | '90'}
          onChange={v => setPeriod(Number(v) as Period)}
          options={[
            { value: '7', label: '近 7 天' },
            { value: '30', label: '近 30 天' },
            { value: '90', label: '近 90 天' },
          ]}
        />
        {report?.markdown && (
          <Button size="sm" variant="ghost" icon={<Copy />} onClick={() => void copyMarkdown()}>
            复制报告
          </Button>
        )}
      </div>

      {eda.isLoading ? (
        <div className={s.skel} aria-busy="true" aria-label="正在生成报告">
          <Skeleton height={96} radius={12} />
          <Skeleton height={280} radius={12} />
        </div>
      ) : !report ? (
        <Notice tone="danger" title="报告没能生成" actions={<Button size="sm" onClick={() => void eda.refetch()}>重试</Button>}>
          确认本地学习服务已经启动。
        </Notice>
      ) : (
        <div className={eda.isFetching && !eda.isLoading ? s.refetching : undefined}>
          <StatRow report={report} />

          <Figure
            title="每天学了多久"
            caption={trendCaption(report)}
            empty={days.every(d => d.minutes === 0) ? '这段时间还没有专注记录。开一个番茄钟，报告就会开始记录。' : null}
          >
            {tables ? (
              <DataTable
                caption="每日学习分钟"
                head={['日期', '学习分钟', '7 日平均', '番茄钟']}
                rows={days.map(d => [d.date, Math.round(d.minutes), Math.round(d.mean), d.sessions])}
              />
            ) : (
              <TrendChart points={days} label={`近 ${period} 天每日学习分钟与 7 日平均`} />
            )}
          </Figure>

          <div className={s.grid2}>
            {grid && (
              <Figure
                title="什么时候学"
                caption={timeCaption(grid, best)}
                empty={grid.max === 0 ? '还没有足够的记录。' : null}
                foot={!tables && grid.max > 0 ? <HeatScale showWindow={bestHours.size > 0} /> : null}
              >
                {tables ? (
                  <DataTable
                    caption="各时段学习分钟"
                    head={['星期', '学习最多的时段', '当天合计']}
                    rows={grid.weekdays.map((wd, d) => {
                      const row = grid.cells[d]
                      const peak = row.indexOf(Math.max(...row))
                      return [wd, grid.dayTotals[d] > 0 ? `${peak}:00` : '—', formatMinutes(grid.dayTotals[d])]
                    })}
                  />
                ) : (
                  <HeatmapChart grid={grid} bestHours={bestHours} />
                )}
              </Figure>
            )}

            <Figure
              title="专注是怎么结束的"
              caption={outcomes.length ? `${report.summary.pomodoro_count} 次专注里，${outcomes[0].key === 'completed' ? `${outcomes[0].count} 次完整完成` : '还没有完整完成的'}。` : undefined}
              empty={outcomes.length === 0 ? '还没有专注记录。' : null}
            >
              <OutcomeChart outcomes={outcomes} />
              {lengths.some(l => l.count > 0) && (
                <div style={{ marginTop: '1.5rem' }}>
                  <p className={s.figCaption} style={{ margin: '0 0 0.625rem' }}>
                    每次专注的时长
                  </p>
                  {tables ? (
                    <DataTable caption="专注时长分布" head={['时长', '次数']} rows={lengths.map(l => [l.label, l.count])} />
                  ) : (
                    <LengthChart buckets={lengths} />
                  )}
                </div>
              )}
            </Figure>
          </div>

          <div className={s.grid2}>
            <Figure title="教练的观察">
              {(report.insights ?? []).length === 0 ? (
                <p className={s.figCaption}>暂时没有需要特别留意的地方。</p>
              ) : (
                <ul className={s.insights}>
                  {report.insights.map((it, i) => (
                    <li key={i} className={s.insight} data-severity={it.severity}>
                      {it.severity === 'high' ? <AlertTriangle aria-hidden /> : it.severity === 'medium' ? <Lightbulb aria-hidden /> : <Info aria-hidden />}
                      <div>
                        <p className={s.insightTitle}>{it.title}</p>
                        <p className={s.insightBody}>{it.detail}</p>
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </Figure>
            <Figure title="可以试试">
              {(report.recommendations ?? []).length === 0 ? (
                <p className={s.figCaption}>保持现在的节奏就好。</p>
              ) : (
                <ol className={s.actions}>
                  {report.recommendations.slice(0, 5).map((r, i) => (
                    <li key={i}>{r}</li>
                  ))}
                </ol>
              )}
            </Figure>
          </div>
        </div>
      )}

      <ProfileSection report={report ?? undefined} profile={profile.data} loading={profile.isLoading} flash={flash === 'report-profile'} />

      {weekly.data && (weekly.data.next_steps ?? []).length > 0 && (
        <Figure title="下周先做什么" caption="从你本周的记录里挑出的最多三件事，不会自动改动计划。" style={{ marginTop: '1.5rem' }}>
          <ul className={s.insights}>
            {weekly.data.next_steps.map((st, i) => {
              const route = safeInternalRoute(st.route)
              return (
                <li key={i} className={s.insight} style={{ gridTemplateColumns: '1.125rem minmax(0,1fr) auto', alignItems: 'center' }}>
                  <BookOpenCheck aria-hidden />
                  <div>
                    <p className={s.insightTitle}>{st.title}</p>
                    <p className={s.insightBody}>
                      约 {st.estimated_minutes} 分钟 · {st.reason}
                    </p>
                  </div>
                  {route && (
                    <IconButton label={`去做：${st.title}`} onClick={() => navigate(route)}>
                      <ArrowRight />
                    </IconButton>
                  )}
                </li>
              )
            })}
          </ul>
        </Figure>
      )}

      <Behaviour report={north.data} loading={north.isLoading} />

      <Figure
        id="report-today"
        title="今天的状态检查"
        className={flash === 'report-today' ? s.flash : undefined}
        style={{ marginTop: '1.5rem' }}
        tools={
          <Button size="sm" variant="ghost" icon={<RefreshCw />} loading={generating} onClick={() => void regenerate()}>
            重新检查
          </Button>
        }
      >
        {today.isLoading ? (
          <Skeleton height={80} />
        ) : !today.data ? (
          <Empty align="start" icon={<Sparkles />} title="今天还没有检查" body="教练会根据今天的专注、任务和复习情况给出提醒。" />
        ) : (
          <TodayCheck report={today.data} />
        )}
      </Figure>
    </div>
  )
}

/* ============================================================================
   Pieces
   ========================================================================== */

/**
 * Bring a deep-linked section into view once the report has rendered, and
 * return its id briefly so it can flash. Runs once per target.
 */
function useScrollToTarget(target: string | null, ready: boolean): string | null {
  const handled = useRef<string | null>(null)
  const [flash, setFlash] = useState<string | null>(null)
  useEffect(() => {
    if (!target || !ready || handled.current === target) return
    const frame = requestAnimationFrame(() => {
      const el = document.getElementById(target)
      if (!el) return
      handled.current = target
      const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches
      el.scrollIntoView({ behavior: reduced ? 'auto' : 'smooth', block: 'start' })
      el.focus({ preventScroll: true })
      setFlash(target)
    })
    return () => cancelAnimationFrame(frame)
  }, [target, ready])
  useEffect(() => {
    if (!flash) return
    const t = window.setTimeout(() => setFlash(null), 1500)
    return () => window.clearTimeout(t)
  }, [flash])
  return flash
}

function Figure({
  id,
  title,
  caption,
  empty,
  foot,
  tools,
  children,
  className,
  style,
}: {
  id?: string
  title: string
  caption?: string
  empty?: string | null
  foot?: ReactNode
  tools?: ReactNode
  children?: ReactNode
  className?: string
  style?: React.CSSProperties
}) {
  const headingId = id ? `${id}-title` : undefined
  return (
    <figure
      id={id}
      className={[s.figure, id ? s.anchor : '', className ?? ''].filter(Boolean).join(' ')}
      style={style}
      tabIndex={id ? -1 : undefined}
      aria-labelledby={headingId}
    >
      <div className={s.figHead}>
        <div>
          <h2 id={headingId} className={s.figTitle}>
            {title}
          </h2>
          {caption && <p className={s.figCaption}>{caption}</p>}
        </div>
        {tools && <div className={s.figTools}>{tools}</div>}
      </div>
      {empty ? <p className={s.figEmpty}>{empty}</p> : children}
      {!empty && foot && <div className={s.figFoot}>{foot}</div>}
    </figure>
  )
}

function StatRow({ report }: { report: EDAReport }) {
  const sm = report.summary
  const taskRate = sm.total_tasks ? Math.round((sm.completed_tasks / sm.total_tasks) * 100) : null
  return (
    <div className={s.stats} role="group" aria-label="概览">
      <div className={s.stat}>
        <span className={s.statLabel}>累计学习</span>
        <span className={s.statValue}>{formatMinutes(sm.total_minutes)}</span>
        <span className={s.statFoot}>
          {sm.active_days} 天有记录 · 日均 {formatMinutes(sm.avg_daily_minutes)}
        </span>
      </div>
      <div className={s.stat}>
        <span className={s.statLabel}>专注次数</span>
        <span className={s.statValue}>
          {sm.pomodoro_count}
          <small>次</small>
        </span>
        <span className={s.statFoot}>完整完成 {Math.round(sm.completion_rate ?? 0)}%</span>
      </div>
      <div className={s.stat}>
        <span className={s.statLabel}>任务</span>
        <span className={s.statValue}>
          {sm.completed_tasks}
          <small>/ {sm.total_tasks}</small>
        </span>
        <span className={s.statFoot}>{taskRate != null ? `完成 ${taskRate}%` : '这段时间没有任务'}</span>
      </div>
      <div className={s.stat}>
        <span className={s.statLabel}>高效时段</span>
        <span className={s.statValue} style={{ fontSize: sm.best_study_window ? undefined : 'var(--mx-type-body)' }}>
          {sm.best_study_window || '还看不出来'}
        </span>
        <span className={s.statFoot}>{sm.peak_hour != null ? `完成率在 ${sm.peak_hour}:00 最高` : '需要更多专注记录'}</span>
      </div>
    </div>
  )
}

function Behaviour({ report, loading }: { report: NorthStarMetricsReport | null | undefined; loading: boolean }) {
  const m = report?.metrics
  const cell = (label: string, value: number | null | undefined, unit: string, foot: string) => (
    <div className={s.metric}>
      <span className={s.metricLabel}>{label}</span>
      {value == null ? (
        <span className={s.metricValue} data-empty="true">
          样本还不够
        </span>
      ) : (
        <span className={s.metricValue}>
          {Math.round(value)}
          <small style={{ marginLeft: 4, color: 'var(--mx-text-3)', fontSize: 'var(--mx-type-meta)', fontWeight: 500 }}>{unit}</small>
        </span>
      )}
      <span className={s.metricFoot}>{foot}</span>
    </div>
  )
  return (
    <Figure title="学习行为" caption="近 28 天。只统计已过观察期的原始事件，用来看趋势，不把相关当成因果。" style={{ marginTop: '1.5rem' }}>
      {loading ? (
        <Skeleton height={72} />
      ) : !m ? (
        <p className={s.figCaption}>暂时读不到行为数据。</p>
      ) : (
        <div className={s.behaviour}>
          {cell(
            '建议执行率',
            m.suggestion_execution_rate?.value,
            '%',
            `真实行为完成 ${m.suggestion_execution_rate?.completed_by_domain_event_count ?? 0} · 手动确认 ${m.suggestion_execution_rate?.completed_by_user_confirmation_count ?? 0}`,
          )}
          {cell('中断后回来', m.interruption_recovery_time?.value, '分钟', `还没回来 ${m.interruption_recovery_time?.unrecovered_count ?? 0} 次`)}
          {cell('复习按时率', m.review_on_time_rate?.value, '%', `已到观察期 ${m.review_on_time_rate?.denominator ?? 0} 次`)}
          {cell('本周有效学习', m.weekly_effective_study_sessions?.value, '次', '单次至少 15 分钟才算')}
        </div>
      )}
    </Figure>
  )
}

function TodayCheck({ report }: { report: NonNullable<Awaited<ReturnType<typeof getDailyIntervention>>> }) {
  const risk = RISK_META[report.risk_level] ?? RISK_META.medium
  return (
    <>
      <div className={s.today}>
        <div>
          <h3 className={s.todayTitle}>
            {report.push_title || '今天的学习状态'}
            <Badge tone={risk.tone} icon={risk.tone === 'danger' ? <AlertTriangle /> : risk.tone === 'warning' ? <Info /> : undefined}>
              {risk.label}
            </Badge>
          </h3>
          <p className={s.todayBody}>{report.summary || report.push_body}</p>
        </div>
      </div>
      <div className={s.cols}>
        {(report.highlights ?? []).length > 0 && (
          <div>
            <p className={s.colTitle}>今天的数据</p>
            <ul className={s.actions}>
              {report.highlights.map((h, i) => (
                <li key={i}>{h}</li>
              ))}
            </ul>
          </div>
        )}
        {(report.suggestions ?? []).length > 0 && (
          <div>
            <p className={s.colTitle}>建议</p>
            <ul className={s.actions}>
              {report.suggestions.map((h, i) => (
                <li key={i}>{h}</li>
              ))}
            </ul>
          </div>
        )}
      </div>
      <p className={s.note}>检查于 {shortMD(report.date)}。重新检查会按现在的数据再算一次。</p>
    </>
  )
}
