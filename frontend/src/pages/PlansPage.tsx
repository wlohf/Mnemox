import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Alert, Button, Calendar, DatePicker, Empty, List, Segmented, Space, Tag, Timeline, Typography, Input, message } from 'antd'
import {
  BulbOutlined,
  CalendarOutlined,
  ClockCircleOutlined,
  EditOutlined,
  FileTextOutlined,
  PlusOutlined,
  QuestionCircleOutlined,
  RobotOutlined,
  SaveOutlined,
  UnorderedListOutlined,
} from '@ant-design/icons'
import dayjs, { Dayjs } from 'dayjs'
import isoWeek from 'dayjs/plugin/isoWeek'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { getApiErrorMessage } from '../services/apiClient'
import { listPlans, savePlan, getPlan, readPlanDraft, writePlanDraft, type PlanItem } from '../services/planApi'
import { generateDailyPlan } from '../services/learningApi'
import { generateFeynmanProbe, type FeynmanProbeResult } from '../services/feynmanProbeApi'
import { confirmCoachNudgeDraft, getCoachNudgeDraft, type CoachNudgeDraft } from '../services/coachApi'
import { MarkdownLiveEditor } from '../components/MarkdownLiveEditor'
import { captureApiSession } from '../services/sessionScope'
import { PageShell } from '../components/PageShell'

dayjs.extend(isoWeek)

const { Text, Paragraph } = Typography

type Plan = PlanItem

interface ChecklistItem {
  id: string
  title: string
  done: boolean
}

function normalizeDateParam(value: string | null | undefined) {
  if (!value || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return dayjs().format('YYYY-MM-DD')
  const parsed = dayjs(value)
  return parsed.isValid() ? parsed.format('YYYY-MM-DD') : dayjs().format('YYYY-MM-DD')
}

function getStats(content: string) {
  let total = 0
  let completed = 0
  for (const line of content.split('\n')) {
    if (/^- \[ \] /.test(line)) total += 1
    else if (/^- \[x\] /i.test(line)) {
      total += 1
      completed += 1
    }
  }
  return { total, completed }
}

function extractChecklistItems(content: string): ChecklistItem[] {
  return content
    .split('\n')
    .map((line, index) => {
      const matched = line.match(/^\s*[-*]\s+\[([ xX])\]\s+(.+)$/)
      if (!matched) return null
      return {
        id: `${index}-${matched[2]}`,
        done: matched[1].toLowerCase() === 'x',
        title: matched[2].replace(/<!-- task:\d+:v\d+ -->/g, '').trim(),
      }
    })
    .filter((item): item is ChecklistItem => Boolean(item))
}

type ViewMode = 'list' | 'timeline'
type QuickRange = 'this_week' | 'last_week' | 'this_month' | 'custom'

function getRangeForQuick(q: QuickRange): [Dayjs, Dayjs] {
  const today = dayjs()
  if (q === 'this_week') return [today.startOf('isoWeek'), today.endOf('isoWeek')]
  if (q === 'last_week') return [today.subtract(1, 'week').startOf('isoWeek'), today.subtract(1, 'week').endOf('isoWeek')]
  if (q === 'this_month') return [today.startOf('month'), today.endOf('month')]
  return [today.subtract(90, 'day'), today]
}

export function PlansPage() {
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const routeDate = normalizeDateParam(searchParams.get('date'))
  const coachAttemptId = searchParams.get('coach_attempt')?.trim() || null
  const coachNudgeId = searchParams.get('coach_nudge')?.trim() || null

  const [plans, setPlans] = useState<Plan[]>([])
  const [loading, setLoading] = useState(false)
  const [activeDate, setActiveDate] = useState(routeDate)
  const [editContent, setEditContent] = useState('')
  const editor = useRef({ date: '', version: 0, dirty: false })
  const loadedDate = useRef('')
  const loadGeneration = useRef(0)
  const [conflict, setConflict] = useState<PlanItem | null>(null)
  const [saving, setSaving] = useState(false)
  const [generating, setGenerating] = useState(false)
  const [probing, setProbing] = useState(false)
  const [probeResult, setProbeResult] = useState<FeynmanProbeResult | null>(null)
  const [filter, setFilter] = useState<'all' | 'has_tasks' | 'incomplete'>('all')
  const [viewMode, setViewMode] = useState<ViewMode>('list')
  const [quickRange, setQuickRange] = useState<QuickRange>('this_week')
  const [customRange, setCustomRange] = useState<[Dayjs, Dayjs]>([dayjs().subtract(90, 'day'), dayjs()])
  const [calendarValue, setCalendarValue] = useState<Dayjs>(dayjs(routeDate))
  const [coachDraft, setCoachDraft] = useState<CoachNudgeDraft | null>(null)
  const [coachDraftLoading, setCoachDraftLoading] = useState(false)
  const [coachDraftConfirming, setCoachDraftConfirming] = useState(false)

  const [rangeStart, rangeEnd] = quickRange === 'custom' ? customRange : getRangeForQuick(quickRange)

  const loadPlans = useCallback(async () => {
    setLoading(true)
    const generation = ++loadGeneration.current
    const scope = captureApiSession()
    try {
      const today = dayjs()
      const selected = dayjs(activeDate)
      const defaultStart = today.subtract(90, 'day')
      const start = selected.isBefore(defaultStart, 'day') ? selected : defaultStart
      const end = selected.isAfter(today, 'day') ? selected : today
      const data = await listPlans(start.format('YYYY-MM-DD'), end.format('YYYY-MM-DD'))
      scope.assertActive()
      if (generation !== loadGeneration.current) return
      loadedDate.current = activeDate
      setPlans((data || []).sort((a, b) => b.date.localeCompare(a.date)))
    } finally {
      if (generation === loadGeneration.current) setLoading(false)
    }
  }, [activeDate])

  useEffect(() => {
    void loadPlans()
  }, [loadPlans])

  useEffect(() => {
    if (!coachNudgeId || !coachAttemptId) {
      setCoachDraft(null)
      return
    }
    let cancelled = false
    setCoachDraftLoading(true)
    void getCoachNudgeDraft(coachNudgeId).then((draft) => {
      if (!cancelled) setCoachDraft(draft)
    }).finally(() => {
      if (!cancelled) setCoachDraftLoading(false)
    })
    return () => { cancelled = true }
  }, [coachAttemptId, coachNudgeId])

  useEffect(() => {
    if (searchParams.get('date') !== routeDate) {
      const next = new URLSearchParams(searchParams)
      next.set('date', routeDate)
      setSearchParams(next, { replace: true })
    }
    if (routeDate !== activeDate) {
      setActiveDate(routeDate)
      setCalendarValue(dayjs(routeDate))
      setProbeResult(null)
    }
  }, [activeDate, routeDate, searchParams, setSearchParams])

  const activePlan = useMemo(() => plans.find((p) => p.date === activeDate) || null, [activeDate, plans])

  useEffect(() => {
    if (editor.current.date !== activeDate) {
      const draft = readPlanDraft(activeDate)
      editor.current = { date: activeDate, version: draft?.version ?? activePlan?.version ?? 0, dirty: Boolean(draft) }
      setEditContent(draft?.content ?? activePlan?.content ?? '')
      setConflict(null)
    }
    if (loadedDate.current !== activeDate) return
    if (editor.current.date === activeDate && editor.current.dirty) return
    const draft = readPlanDraft(activeDate)
    editor.current = { date: activeDate, version: draft?.version ?? activePlan?.version ?? 0, dirty: Boolean(draft) }
    setEditContent(draft?.content ?? activePlan?.content ?? '')
    setProbeResult(null)
  }, [activeDate, activePlan, loading])

  const updateEditor = (content: string) => {
    editor.current.dirty = true
    setEditContent(content)
    writePlanDraft(activeDate, { content, version: editor.current.version })
  }


  const openDocument = useCallback((date: Dayjs | string, replace = false) => {
    const dateStr = typeof date === 'string' ? normalizeDateParam(date) : date.format('YYYY-MM-DD')
    setActiveDate(dateStr)
    setCalendarValue(dayjs(dateStr))
    setProbeResult(null)
    const next = new URLSearchParams(searchParams)
    next.set('date', dateStr)
    setSearchParams(next, { replace })
  }, [searchParams, setSearchParams])

  const upsertPlan = (plan: Plan) => {
    setPlans((prev) => {
      const exists = prev.some((p) => p.date === plan.date)
      const next = exists ? prev.map((p) => (p.date === plan.date ? plan : p)) : [plan, ...prev]
      return next.sort((a, b) => b.date.localeCompare(a.date))
    })
  }

  const handleSave = async () => {
    setSaving(true)
    try {
      const scope = captureApiSession()
      const saved = await savePlan(activeDate, editContent, editor.current.version)
      scope.assertActive()
      const newerDraft = readPlanDraft(activeDate)
      const nextPlan = saved || { date: activeDate, content: editContent }
      upsertPlan(nextPlan)
      if (!newerDraft || newerDraft.content === editContent) {
        writePlanDraft(activeDate, null)
        if (editor.current.date === activeDate) {
          editor.current = { date: activeDate, version: saved.version ?? 0, dirty: false }
          setEditContent(nextPlan.content)
          setConflict(null)
        }
        message.success('已保存')
      } else {
        message.success('提交的版本已保存；保存期间新增的编辑仍保留为草稿')
      }
    } catch (error) {
      message.error(getApiErrorMessage(error, '保存失败，草稿已保留'))
      if ((error as { status?: number }).status === 409) {
        const latest = await getPlan(activeDate)
        setConflict(latest)
      }
    } finally {
      setSaving(false)
    }
  }

  const handleGenerate = async (date: string) => {
    setGenerating(true)
    const baseVersion = date === activeDate ? editor.current.version : (plans.find(p => p.date === date)?.version ?? 0)
    try {
      const scope = captureApiSession()
      const result = await generateDailyPlan(date)
      scope.assertActive()
      // Generation appends to the current local draft; saving is explicit.
      const latestDraft = readPlanDraft(date)
      const current = latestDraft?.content ?? (date === activeDate ? editContent : (plans.find(p => p.date === date)?.content ?? ''))
      const content = [current, result.content || ''].filter(Boolean).join('\n\n')
      const version = latestDraft?.version ?? baseVersion
      writePlanDraft(date, { content, version })
      editor.current = { date, version, dirty: true }
      openDocument(date)
      setEditContent(content)
      message.success(`已追加 ${result.item_count} 项到草稿，请检查后保存`)

    } catch (error) {
      message.error(getApiErrorMessage(error, '生成计划失败'))
    } finally {
      setGenerating(false)
    }
  }

  const handleFeynmanProbe = async () => {
    if (editContent.trim().length < 12) {
      message.warning('请先写一段今日复盘或总结')
      return
    }
    setProbing(true)
    try {
      const result = await generateFeynmanProbe(activeDate, editContent, 4)
      if (!result) {
        message.error('明镜追问生成失败，请稍后重试')
        return
      }
      setProbeResult(result)
      message.success(result.fallback ? '已生成基础追问' : '已生成明镜追问')
    } finally {
      setProbing(false)
    }
  }

  const confirmCoachDraft = async () => {
    if (!coachDraft || !coachNudgeId || !coachAttemptId) return
    setCoachDraftConfirming(true)
    try {
      const confirmed = await confirmCoachNudgeDraft(coachNudgeId, coachAttemptId)
      if (!confirmed) {
        message.error('草案确认失败，请刷新后重试')
        return
      }
      const planDate = String(confirmed.result.created?.plan?.date || coachDraft.draft.date || activeDate)
      message.success(confirmed.result.message || '已确认并加入今日计划')
      setCoachDraft(null)
      setSearchParams({ date: normalizeDateParam(planDate) }, { replace: true })
      void loadPlans()
    } finally {
      setCoachDraftConfirming(false)
    }
  }

  const appendProbeToPlan = () => {
    if (!probeResult) return
    const block = [
      '',
      '---',
      '',
      `## ${probeResult.name}`,
      `> ${probeResult.tagline}`,
      '',
      `**讲得比较清楚的地方：** ${probeResult.strongest_part}`,
      '',
      '**小白会追问：**',
      ...probeResult.questions.map((q, idx) => `${idx + 1}. **${q.type}**：${q.question}\n   - 为什么问：${q.why}`),
      '',
      `**下一步最小补缺口：** ${probeResult.next_focus}`,
      '',
    ].join('\n')
    updateEditor(`${editContent.trimEnd()}\n${block}`)
    message.success('已追加到计划')
  }

  const filtered = useMemo(() => {
    return plans.filter((p) => {
      const d = dayjs(p.date)
      const inRange = !d.isBefore(rangeStart, 'day') && !d.isAfter(rangeEnd, 'day')
      if (!inRange) return false
      if (filter === 'all') return true
      const { total, completed } = getStats(p.content)
      if (filter === 'has_tasks') return total > 0
      if (filter === 'incomplete') return total > 0 && completed < total
      return true
    })
  }, [plans, filter, rangeStart, rangeEnd])

  const planDateSet = useMemo(() => {
    return new Set(
      plans
        .filter((p) => (p.content || '').trim().length > 0)
        .map((p) => p.date),
    )
  }, [plans])

  const activeStats = getStats(editContent)
  const activeTasks = useMemo(() => extractChecklistItems(editContent), [editContent])
  const isToday = activeDate === dayjs().format('YYYY-MM-DD')
  const isDirty = editContent !== (activePlan?.content || '')

  const planRow = (plan: Plan) => {
    const { total, completed } = getStats(plan.content)
    const firstLine = plan.content.split('\n').find((line) => line.trim() && !line.startsWith('#')) || ''
    const selected = plan.date === activeDate
    return (
      <button
        type="button"
        className={`mnemox-plan-file${selected ? ' is-active' : ''}`}
        onClick={() => openDocument(plan.date)}
      >
        <span className="mnemox-plan-file-title">
          <FileTextOutlined />
          <span>{plan.date}</span>
          {plan.date === dayjs().format('YYYY-MM-DD') && <Tag color="orange">今天</Tag>}
        </span>
        <span className="mnemox-plan-file-preview">{firstLine || '空白计划'}</span>
        {total > 0 && <span className="mnemox-plan-file-meta">{completed}/{total} 完成</span>}
      </button>
    )
  }

  return (
    <PageShell
      title={(
        <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <CalendarOutlined style={{ fontSize: 18, color: 'var(--accent-600)' }} />
          <span>学习计划</span>
        </span>
      )}
      onBack={() => navigate('/')}
      rightExtra={(
        <Space wrap>
          <Button icon={<PlusOutlined />} onClick={() => openDocument(dayjs())}>今天</Button>
          <Button icon={<RobotOutlined />} loading={generating} onClick={() => handleGenerate(activeDate)}>
            生成草稿当前计划
          </Button>
          <Button type="primary" icon={<SaveOutlined />} loading={saving} onClick={handleSave}>
            保存
          </Button>
        </Space>
      )}
      maxWidth={1540}
    >
      {(coachDraft || coachDraftLoading) && (
        <Alert
          type="info"
          showIcon
          message={coachDraft?.nudge.title || 'Coach 已准备一份待确认草案'}
          description={coachDraft
            ? `将加入：${(coachDraft.draft.items || []).map((item) => item.title).filter(Boolean).join('；') || '最小学习计划'}。确认前不会写入计划。`
            : '正在读取草案内容…'}
          action={coachDraft ? (
            <Button type="primary" size="small" loading={coachDraftConfirming} onClick={() => void confirmCoachDraft()}>
              确认加入计划
            </Button>
          ) : undefined}
          style={{ marginBottom: 16 }}
        />
      )}
      <div className="mnemox-plan-workbench">
        <aside className="mnemox-plan-sidebar">
          <div className="mnemox-panel-heading">
            <span>计划日历</span>
            <Tag>{plans.length}</Tag>
          </div>
          <Calendar
            className="mnemox-plan-calendar"
            fullscreen={false}
            value={calendarValue}
            onPanelChange={(value) => setCalendarValue(value)}
            onSelect={(value) => openDocument(value)}
            cellRender={(current, info) => {
              if (info.type !== 'date') return null
              const hasPlan = planDateSet.has(current.format('YYYY-MM-DD'))
              return hasPlan ? <span className="mnemox-plan-calendar-dot" /> : null
            }}
          />

          <div className="mnemox-plan-sidebar-section">
            <Segmented
              value={quickRange}
              onChange={(v) => setQuickRange(v as QuickRange)}
              options={[
                { label: '本周', value: 'this_week' },
                { label: '上周', value: 'last_week' },
                { label: '本月', value: 'this_month' },
                { label: '自定义', value: 'custom' },
              ]}
              size="small"
            />
            {quickRange === 'custom' && (
              <DatePicker.RangePicker
                size="small"
                value={customRange}
                onChange={(value) => value && setCustomRange([value[0]!, value[1]!])}
              />
            )}
            <Segmented
              value={filter}
              onChange={(v) => setFilter(v as typeof filter)}
              options={[
                { label: '全部', value: 'all' },
                { label: '有任务', value: 'has_tasks' },
                { label: '未完成', value: 'incomplete' },
              ]}
              size="small"
            />
          </div>
        </aside>

        <aside className="mnemox-plan-list-pane">
          <div className="mnemox-panel-heading">
            <span>计划文件</span>
            <Space size={4}>
              <Button size="small" type={viewMode === 'list' ? 'primary' : 'text'} icon={<UnorderedListOutlined />} onClick={() => setViewMode('list')} />
              <Button size="small" type={viewMode === 'timeline' ? 'primary' : 'text'} icon={<ClockCircleOutlined />} onClick={() => setViewMode('timeline')} />
            </Space>
          </div>
          {viewMode === 'list' ? (
            <List
              loading={loading}
              dataSource={filtered}
              locale={{ emptyText: <Empty description="该时间段暂无计划" /> }}
              renderItem={(plan) => <List.Item>{planRow(plan)}</List.Item>}
            />
          ) : (
            loading ? (
              <div className="mnemox-pane-empty">加载中...</div>
            ) : filtered.length === 0 ? (
              <Empty description="该时间段暂无计划" />
            ) : (
              <Timeline
                className="mnemox-plan-timeline"
                items={filtered.map((plan) => {
                  const { total, completed } = getStats(plan.content)
                  return {
                    color: plan.date === activeDate ? 'orange' : completed === total && total > 0 ? 'green' : 'blue',
                    children: planRow(plan),
                  }
                })}
              />
            )
          )}
        </aside>

        <main className="mnemox-plan-document">
          <div className="mnemox-doc-breadcrumb">学习计划 / 日志 / {activeDate}</div>
          <div className="mnemox-doc-header">
            <h1>{activeDate}</h1>
            <Space wrap>
              {isToday && <Tag color="orange">今天</Tag>}
              {isDirty && <Tag color="gold">未保存</Tag>}
              <Tag>{activeStats.completed}/{activeStats.total} 任务</Tag>
            </Space>
          </div>
          <div className="mnemox-doc-toolbar">
            <Button size="small" icon={<RobotOutlined />} loading={generating} onClick={() => handleGenerate(activeDate)}>
              生成草稿
            </Button>
            <Button size="small" icon={<QuestionCircleOutlined />} loading={probing} onClick={handleFeynmanProbe}>
              明镜追问
            </Button>
            <Button size="small" type="primary" icon={<SaveOutlined />} loading={saving} onClick={handleSave}>
              保存
            </Button>
          </div>
          {conflict?.date === activeDate && <Alert type="warning" message="服务器内容已更新，你的草稿仍保留在本机" description={<Space direction="vertical" style={{ width: '100%' }}>
            <Input.TextArea readOnly value={conflict.content} aria-label="服务器最新计划" rows={6} />
            <Button onClick={() => {
              const merged = `${conflict.content}\n\n## 保留的本地草稿（待整理）\n${editContent.replace(/<!-- task:\d+:v\d+ -->/g, '')}`
              editor.current.version = conflict.version ?? 0
              updateEditor(merged)
              setConflict(null)
              message.info('两份内容均已保留在编辑区；任务关联采用服务器最新状态，请整理后保存')
            }}>保留两份并继续编辑</Button>
          </Space>} />}
          <MarkdownLiveEditor
            value={editContent}
            onChange={updateEditor}
            height="calc(100vh - 330px)"
            className="mnemox-plan-editor"
            placeholder={`# ${activeDate}\n\n- [ ] `}
          />
          {probeResult && (
            <div className="mnemox-probe-panel">
              <div className="mnemox-probe-title">
                <Space>
                  <BulbOutlined style={{ color: 'var(--accent-600)' }} />
                  <span>{probeResult.name}</span>
                  {probeResult.fallback && <Tag color="orange">基础追问</Tag>}
                </Space>
                <Button size="small" onClick={appendProbeToPlan}>追加到计划</Button>
              </div>
              <Alert type="info" showIcon message={probeResult.tagline} style={{ marginBottom: 12 }} />
              <Paragraph style={{ marginBottom: 8 }}>
                <Text strong>讲得比较清楚：</Text>{probeResult.strongest_part}
              </Paragraph>
              <List
                size="small"
                dataSource={probeResult.questions}
                renderItem={(q, idx) => (
                  <List.Item style={{ display: 'block', paddingLeft: 0, paddingRight: 0 }}>
                    <Space size={6} wrap style={{ marginBottom: 4 }}>
                      <Tag color="purple">{idx + 1}</Tag>
                      <Tag>{q.type}</Tag>
                    </Space>
                    <Paragraph style={{ marginBottom: 4 }}>{q.question}</Paragraph>
                    <Text type="secondary" style={{ fontSize: 12 }}>为什么问：{q.why}</Text>
                  </List.Item>
                )}
              />
            </div>
          )}
        </main>

        <aside className="mnemox-plan-context-pane">
          <div className="mnemox-panel-heading">
            <span>当天任务</span>
            <Button type="text" size="small" icon={<EditOutlined />} onClick={() => openDocument(activeDate)} />
          </div>
          {activeTasks.length === 0 ? (
            <div className="mnemox-pane-empty">暂无任务</div>
          ) : (
            <div className="mnemox-task-list">
              {activeTasks.map((task) => (
                <div key={task.id} className={`mnemox-task-row${task.done ? ' is-done' : ''}`}>
                  <span className="mnemox-task-check">{task.done ? '✓' : ''}</span>
                  <span>{task.title}</span>
                </div>
              ))}
            </div>
          )}
          <div className="mnemox-plan-inspector">
            <div>
              <span>日期</span>
              <strong>{dayjs(activeDate).format('YYYY年MM月DD日')}</strong>
            </div>
            <div>
              <span>字数</span>
              <strong>{editContent.trim().length}</strong>
            </div>
            <div>
              <span>完成率</span>
              <strong>{activeStats.total ? Math.round((activeStats.completed / activeStats.total) * 100) : 0}%</strong>
            </div>
          </div>
        </aside>
      </div>
    </PageShell>
  )
}
