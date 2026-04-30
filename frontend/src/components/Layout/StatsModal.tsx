import { useMemo } from 'react'
import { Modal, Card, Row, Col, Segmented } from 'antd'
import { BarChartOutlined } from '@ant-design/icons'
import ReactECharts from 'echarts-for-react'
import type { DateRange } from '../../stores/pomodoroStore'

interface StatsModalProps {
  open: boolean
  onClose: () => void
  stats: {
    todayCount: number
    todayMinutes: number
    weekCount: number
    weekMinutes: number
    weeklyData: Array<{ date: string; count: number; minutes: number }>
  }
  statsRange: DateRange
  setStatsRange: (r: DateRange) => void
  getCumulativeStats: () => { totalCount: number; totalHours: number; dailyAverageMinutes: number }
  getTaskDistribution: (range: DateRange) => Array<{ taskName: string; minutes: number; count: number; percentage: number; color: string }>
  weekChartOption: object
}

export function StatsModal({ open, onClose, stats, statsRange, setStatsRange, getCumulativeStats, getTaskDistribution, weekChartOption }: StatsModalProps) {
  const cumulativeStats = useMemo(() => getCumulativeStats(), [getCumulativeStats])
  const distribution = useMemo(() => getTaskDistribution(statsRange), [getTaskDistribution, statsRange])
  const totalMinutes = distribution.reduce((sum, t) => sum + t.minutes, 0)

  const pieOption = useMemo(() => ({
    tooltip: {
      trigger: 'item',
      backgroundColor: 'rgba(255,255,255,0.95)',
      borderColor: 'rgba(0,0,0,0.1)',
      borderWidth: 1,
      textStyle: { color: 'var(--text-primary)', fontSize: 12 },
      formatter: (params: any) => {
        const h = Math.floor(params.data.minutes / 60)
        const m = params.data.minutes % 60
        return `<b>${params.name}</b><br/>⏱️ ${h > 0 ? `${h}h ` : ''}${m}m<br/>🍅 ${params.data.count}个 (${params.percent}%)`
      },
    },
    legend: { orient: 'vertical', right: 10, top: 'center', itemWidth: 10, itemHeight: 10, textStyle: { fontSize: 11, color: 'var(--text-secondary)' } },
    series: [{
      type: 'pie', radius: ['45%', '70%'], center: ['35%', '50%'], avoidLabelOverlap: true,
      itemStyle: { borderRadius: 4, borderColor: 'var(--bg-surface)', borderWidth: 2 },
      label: { show: false },
      emphasis: { label: { show: true, fontSize: 12, fontWeight: 'bold' }, itemStyle: { shadowBlur: 10, shadowOffsetX: 0, shadowColor: 'rgba(0,0,0,0.2)' } },
      data: distribution.map((t) => ({ value: t.minutes, name: t.taskName, minutes: t.minutes, count: t.count, itemStyle: { color: t.color } })),
    }],
  }), [distribution])

  return (
    <Modal
      title={<span><BarChartOutlined /> 番茄钟统计</span>}
      open={open}
      onCancel={onClose}
      footer={null}
      width={680}
      styles={{ body: { padding: '16px 24px' } }}
    >
      {/* 累计统计 */}
      <Card size="small" style={{ marginBottom: 16, background: 'linear-gradient(135deg,rgba(255,77,79,0.08) 0%,rgba(255,149,0,0.08) 100%)', border: '1px solid rgba(255,77,79,0.15)' }}>
        <div style={{ textAlign: 'center', marginBottom: 8 }}>
          <span style={{ fontSize: 13, color: 'var(--text-secondary)' }}>累计专注</span>
        </div>
        <Row gutter={16}>
          {[
            { value: cumulativeStats.totalCount, unit: '', label: '次数', color: '#ff4d4f' },
            { value: cumulativeStats.totalHours, unit: 'h', label: '时长', color: '#007AFF' },
            { value: cumulativeStats.dailyAverageMinutes, unit: 'm', label: '日均', color: '#34C759' },
          ].map((s) => (
            <Col key={s.label} span={8} style={{ textAlign: 'center' }}>
              <div style={{ fontSize: 32, fontWeight: 'bold', color: s.color }}>{s.value}<span style={{ fontSize: 14, fontWeight: 'normal' }}>{s.unit}</span></div>
              <div style={{ fontSize: 12, color: 'var(--text-tertiary)' }}>{s.label}</div>
            </Col>
          ))}
        </Row>
      </Card>

      {/* 范围选择 */}
      <div style={{ marginBottom: 16, textAlign: 'center' }}>
        <Segmented
          value={statsRange}
          onChange={(v) => setStatsRange(v as DateRange)}
          options={[{ label: '日', value: 'day' }, { label: '周', value: 'week' }, { label: '月', value: 'month' }, { label: '全部', value: 'all' }]}
          style={{ background: 'rgba(0,0,0,0.04)', padding: 2 }}
        />
      </div>

      {/* 当前范围统计 */}
      <Row gutter={16} style={{ marginBottom: 16 }}>
        {[
          { value: stats.todayCount, label: '今日番茄', bg: 'rgba(251, 113, 133, 0.1)', color: 'var(--rose-400)' },
          { value: stats.todayMinutes, label: '今日分钟', bg: 'rgba(99, 102, 241, 0.1)', color: 'var(--brand-400)' },
          { value: stats.weekCount, label: '本周番茄', bg: 'rgba(45, 212, 191, 0.1)', color: 'var(--teal-400)' },
          { value: Math.round(stats.weekMinutes / 60), label: '本周小时', bg: 'rgba(251, 191, 36, 0.1)', color: 'var(--amber-400)' },
        ].map((s) => (
          <Col key={s.label} span={6}>
            <Card size="small" style={{ textAlign: 'center', background: s.bg }}>
              <div style={{ fontSize: 20, fontWeight: 'bold', color: s.color }}>{s.value}</div>
              <div style={{ fontSize: 11, color: 'var(--text-tertiary)' }}>{s.label}</div>
            </Card>
          </Col>
        ))}
      </Row>

      {/* 分布图 */}
      {distribution.length === 0 ? (
        <Card size="small" title="专注时长分布" style={{ marginBottom: 16 }}>
          <div style={{ textAlign: 'center', padding: '40px 0', color: 'var(--text-tertiary)' }}>暂无数据，开始专注计时吧</div>
        </Card>
      ) : (
        <Card
          size="small"
          title={
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span>专注时长分布</span>
              <span style={{ fontSize: 12, color: 'var(--text-tertiary)', fontWeight: 'normal' }}>共 {Math.floor(totalMinutes / 60)}h {totalMinutes % 60}m</span>
            </div>
          }
          style={{ marginBottom: 16 }}
        >
          <ReactECharts option={pieOption} style={{ height: 200 }} />
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2,1fr)', gap: 8, marginTop: 12, paddingTop: 12, borderTop: '1px solid rgba(0,0,0,0.06)' }}>
            {distribution.slice(0, 6).map((task) => (
              <div key={task.taskName} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '6px 8px', background: 'rgba(0,0,0,0.02)', borderRadius: 6 }}>
                <div style={{ width: 10, height: 10, borderRadius: 3, background: task.color, flexShrink: 0 }} />
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 12, fontWeight: 500, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{task.taskName}</div>
                  <div style={{ fontSize: 11, color: 'var(--text-tertiary)' }}>{Math.floor(task.minutes / 60)}h {task.minutes % 60}m · {task.percentage}%</div>
                </div>
              </div>
            ))}
          </div>
        </Card>
      )}

      {/* 本周趋势 */}
      <Card size="small" title="本周趋势">
        <ReactECharts option={weekChartOption} style={{ height: 160 }} />
      </Card>
    </Modal>
  )
}
