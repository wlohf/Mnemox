import { useState, useEffect, useMemo } from 'react'
import { Card, List, Button, Modal, Input, Tag, Empty, Segmented, message, DatePicker, Timeline, Calendar } from 'antd'
import { CalendarOutlined, PlusOutlined, EditOutlined, UnorderedListOutlined, ClockCircleOutlined, ArrowLeftOutlined } from '@ant-design/icons'
import dayjs, { Dayjs } from 'dayjs'
import isoWeek from 'dayjs/plugin/isoWeek'
import { apiFetch } from '../services/apiClient'
import { generateDailyPlan } from '../services/learningApi'
import { useNavigate } from 'react-router-dom'

dayjs.extend(isoWeek)

interface Plan {
  date: string
  content: string
}

function getStats(content: string) {
  let total = 0, completed = 0
  for (const line of content.split('\n')) {
    if (/^- \[ \] /.test(line)) total++
    else if (/^- \[x\] /.test(line)) { total++; completed++ }
  }
  return { total, completed }
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
  const [plans, setPlans] = useState<Plan[]>([])
  const [loading, setLoading] = useState(false)
  const [editingPlan, setEditingPlan] = useState<Plan | null>(null)
  const [editContent, setEditContent] = useState('')
  const [saving, setSaving] = useState(false)
  const [generating, setGenerating] = useState(false)
  const [filter, setFilter] = useState<'all' | 'has_tasks' | 'incomplete'>('all')
  const [viewMode, setViewMode] = useState<ViewMode>('list')
  const [quickRange, setQuickRange] = useState<QuickRange>('this_week')
  const [customRange, setCustomRange] = useState<[Dayjs, Dayjs]>([dayjs().subtract(90, 'day'), dayjs()])
  const [calendarValue, setCalendarValue] = useState<Dayjs>(dayjs())

  const [rangeStart, rangeEnd] = quickRange === 'custom' ? customRange : getRangeForQuick(quickRange)

  const loadPlans = async () => {
    setLoading(true)
    try {
      const end = dayjs().format('YYYY-MM-DD')
      const start = dayjs().subtract(90, 'day').format('YYYY-MM-DD')
      const data = await apiFetch<Plan[]>(`/api/plans/?start=${start}&end=${end}`)
      setPlans((data || []).reverse())
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { loadPlans() }, [])

  const handleSave = async () => {
    if (!editingPlan) return
    setSaving(true)
    try {
      const saved = await apiFetch<Plan>(`/api/plans/${editingPlan.date}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content: editContent }),
      })
      const nextPlan = saved || { ...editingPlan, content: editContent }
      setPlans(prev => {
        const exists = prev.some(p => p.date === nextPlan.date)
        const next = exists
          ? prev.map(p => p.date === nextPlan.date ? nextPlan : p)
          : [nextPlan, ...prev]
        return next.sort((a, b) => b.date.localeCompare(a.date))
      })
      await loadPlans()
      setEditingPlan(null)
      message.success('已保存')
    } finally {
      setSaving(false)
    }
  }

  const handleGenerate = async (date: string) => {
    setGenerating(true)
    try {
      const result = await generateDailyPlan(date)
      if (result) {
        message.success(`已生成计划，共 ${result.item_count} 项`)
        await loadPlans()
      }
    } finally {
      setGenerating(false)
    }
  }

  const handleNewPlan = async () => {
    const today = dayjs().format('YYYY-MM-DD')
    const existing = plans.find(p => p.date === today)
    if (existing) {
      setEditingPlan(existing)
      setEditContent(existing.content)
    } else {
      setEditingPlan({ date: today, content: '' })
      setEditContent('')
    }
  }

  const filtered = useMemo(() => {
    return plans.filter(p => {
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

  const openEdit = (plan: Plan) => { setEditingPlan(plan); setEditContent(plan.content) }

  const planCard = (plan: Plan, compact = false) => {
    const { total, completed } = getStats(plan.content)
    const isToday = plan.date === dayjs().format('YYYY-MM-DD')
    const firstLine = plan.content.split('\n').find(l => l.trim() && !l.startsWith('#')) || ''
    return (
      <Card
        size="small"
        style={{
          marginBottom: compact ? 0 : 8,
          borderLeft: isToday ? '3px solid var(--accent-600)' : '3px solid transparent',
          background: isToday ? 'var(--accent-50)' : 'var(--bg-secondary)',
        }}
        bodyStyle={{ padding: '10px 14px' }}
      >
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
              <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-primary)' }}>{plan.date}</span>
              {isToday && <Tag color="orange" style={{ fontSize: 11 }}>今天</Tag>}
              {total > 0 && (
                <Tag color={completed === total ? 'green' : 'blue'} style={{ fontSize: 11 }}>
                  {completed}/{total} 完成
                </Tag>
              )}
            </div>
            <div style={{ fontSize: 12, color: 'var(--text-secondary)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', maxWidth: 480 }}>
              {firstLine || '（空白计划）'}
            </div>
          </div>
          <Button type="text" size="small" icon={<EditOutlined />} onClick={() => openEdit(plan)} style={{ color: 'var(--text-tertiary)', flexShrink: 0 }} />
        </div>
      </Card>
    )
  }

  return (
    <div style={{ maxWidth: 760, margin: '0 auto', padding: '24px 16px' }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <Button
            size="small"
            icon={<ArrowLeftOutlined />}
            onClick={() => navigate('/')}
          >
            返回主页
          </Button>
          <CalendarOutlined style={{ fontSize: 18, color: 'var(--accent-600)' }} />
          <span style={{ fontSize: 18, fontWeight: 600, color: 'var(--text-primary)' }}>学习计划</span>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <Button icon={<PlusOutlined />} size="small" loading={generating} onClick={() => handleGenerate(dayjs().format('YYYY-MM-DD'))}>
            AI 生成今日计划
          </Button>
          <Button icon={<EditOutlined />} size="small" onClick={handleNewPlan}>手动新建</Button>
        </div>
      </div>

      <Card size="small" title="计划日历" style={{ marginBottom: 16 }}>
        <Calendar
          fullscreen={false}
          value={calendarValue}
          onPanelChange={(value) => setCalendarValue(value)}
          onSelect={(value) => {
            const selectedDate = value.format('YYYY-MM-DD')
            const existing = plans.find((p) => p.date === selectedDate)
            if (existing) {
              setEditingPlan(existing)
              setEditContent(existing.content)
            } else {
              setEditingPlan({ date: selectedDate, content: '' })
              setEditContent('')
            }
          }}
          dateCellRender={(current) => {
            const hasPlan = planDateSet.has(current.format('YYYY-MM-DD'))
            if (!hasPlan) return null
            return (
              <div style={{ display: 'flex', justifyContent: 'center', marginTop: 2 }}>
                <span
                  style={{
                    width: 6,
                    height: 6,
                    borderRadius: '50%',
                    background: 'var(--text-primary)',
                    border: '1px solid var(--bg-secondary)',
                    opacity: 0.9,
                    display: 'inline-block',
                  }}
                />
              </div>
            )
          }}
        />
      </Card>

      {/* Range selector */}
      <div style={{ display: 'flex', gap: 8, marginBottom: 12, flexWrap: 'wrap', alignItems: 'center' }}>
        <Segmented
          value={quickRange}
          onChange={v => setQuickRange(v as QuickRange)}
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
            onChange={v => v && setCustomRange([v[0]!, v[1]!])}
          />
        )}
        <div style={{ marginLeft: 'auto', display: 'flex', gap: 4 }}>
          <Button size="small" type={viewMode === 'list' ? 'primary' : 'default'} icon={<UnorderedListOutlined />} onClick={() => setViewMode('list')} />
          <Button size="small" type={viewMode === 'timeline' ? 'primary' : 'default'} icon={<ClockCircleOutlined />} onClick={() => setViewMode('timeline')} />
        </div>
      </div>

      {/* Task filter */}
      <Segmented
        value={filter}
        onChange={v => setFilter(v as typeof filter)}
        options={[
          { label: '全部', value: 'all' },
          { label: '有任务', value: 'has_tasks' },
          { label: '未完成', value: 'incomplete' },
        ]}
        size="small"
        style={{ marginBottom: 16 }}
      />

      {/* List view */}
      {viewMode === 'list' && (
        <List
          loading={loading}
          dataSource={filtered}
          locale={{ emptyText: <Empty description="该时间段暂无计划" /> }}
          renderItem={(plan) => planCard(plan)}
        />
      )}

      {/* Timeline view */}
      {viewMode === 'timeline' && (
        loading
          ? <div style={{ textAlign: 'center', padding: 32, color: 'var(--text-tertiary)' }}>加载中...</div>
          : filtered.length === 0
            ? <Empty description="该时间段暂无计划" />
            : <Timeline
                style={{ marginTop: 8 }}
                items={filtered.map(plan => {
                  const { total, completed } = getStats(plan.content)
                  const isToday = plan.date === dayjs().format('YYYY-MM-DD')
                  return {
                    color: isToday ? 'orange' : completed === total && total > 0 ? 'green' : 'blue',
                    children: planCard(plan, true),
                  }
                })}
              />
      )}

      <Modal
        open={!!editingPlan}
        title={editingPlan ? `${editingPlan.date} 的计划` : ''}
        onOk={handleSave}
        onCancel={() => setEditingPlan(null)}
        confirmLoading={saving}
        width={600}
        okText="保存"
      >
        <div style={{ marginBottom: 8, display: 'flex', gap: 8 }}>
          <Button size="small" loading={generating} onClick={() => editingPlan && handleGenerate(editingPlan.date)}>
            ✨ AI 重新生成
          </Button>
          <span style={{ fontSize: 12, color: 'var(--text-tertiary)', lineHeight: '24px' }}>
            使用 <code>- [ ]</code> 创建可勾选任务
          </span>
        </div>
        <Input.TextArea
          value={editContent}
          onChange={e => setEditContent(e.target.value)}
          autoSize={{ minRows: 10, maxRows: 20 }}
          placeholder={`输入今日计划...\n例如：\n- [ ] 复习第一章\n- [ ] 完成10道练习题`}
        />
      </Modal>
    </div>
  )
}
