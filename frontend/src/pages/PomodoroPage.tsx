import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Layout, Card, Button, Row, Col, Statistic, Segmented } from 'antd'
import { ArrowLeftOutlined, BarChartOutlined } from '@ant-design/icons'
import ReactECharts from 'echarts-for-react'
import { usePomodoroStore, type DateRange } from '../stores/pomodoroStore'

const { Header, Content } = Layout

export function PomodoroPage() {
  const navigate = useNavigate()
  const { getStats, getCumulativeStats, getTaskDistribution } = usePomodoroStore()
  const [range, setRange] = useState<DateRange>('week')

  const stats = getStats()
  const cumulative = getCumulativeStats()
  const distribution = getTaskDistribution(range)

  const weekOption = useMemo(() => ({
    tooltip: {
      trigger: 'axis',
      formatter: (params: any) => {
        const data = params[0]
        const dayData = stats.weeklyData[data.dataIndex]
        const minutes = dayData?.minutes || 0
        return `${['日', '一', '二', '三', '四', '五', '六'][new Date(dayData?.date).getDay()] || ''}<br/>🍅 ${data.value} 个<br/>⏱️ ${minutes.toFixed(1)} 分钟`
      },
    },
    grid: { top: 10, right: 10, bottom: 20, left: 30 },
    xAxis: {
      type: 'category',
      data: stats.weeklyData.map((d) => ['日', '一', '二', '三', '四', '五', '六'][new Date(d.date).getDay()]),
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: { color: '#999', fontSize: 10 },
    },
    yAxis: {
      type: 'value',
      minInterval: 1,
      axisLine: { show: false },
      axisTick: { show: false },
      splitLine: { lineStyle: { color: 'rgba(0,0,0,0.05)' } },
      axisLabel: { color: '#999', fontSize: 10 },
    },
    series: [{
      type: 'bar',
      data: stats.weeklyData.map((d) => d.count),
      barWidth: '50%',
      itemStyle: {
        color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: '#ff7875' }, { offset: 1, color: '#ff4d4f' }] },
        borderRadius: [4, 4, 0, 0],
      },
    }],
  }), [stats.weeklyData])

  const pieOption = useMemo(() => ({
    tooltip: {
      trigger: 'item',
      formatter: (params: any) => {
        const minutes = params.data.minutes as number
        const hours = minutes / 60
        const display = hours >= 1 ? `${hours.toFixed(1)}h` : `${minutes.toFixed(1)}m`
        return `${params.name}<br/>⏱️ ${display}<br/>🍅 ${params.data.count} 个 (${params.percent}%)`
      },
    },
    legend: {
      orient: 'vertical',
      right: 10,
      top: 'center',
      textStyle: { fontSize: 11, color: '#666' },
    },
    series: [{
      type: 'pie',
      radius: ['45%', '70%'],
      center: ['35%', '50%'],
      data: distribution.map((t) => ({
        value: t.minutes,
        name: t.taskName,
        minutes: t.minutes,
        count: t.count,
        itemStyle: { color: t.color },
      })),
      label: { show: false },
      itemStyle: { borderColor: '#fff', borderWidth: 2 },
    }],
  }), [distribution])

  return (
    <Layout style={{ minHeight: '100vh', background: '#f7f8fa' }}>
      <Header style={{ background: '#fff', borderBottom: '1px solid #f0f0f0', paddingInline: 16 }}>
        <div style={{ maxWidth: 1200, margin: '0 auto', display: 'flex', alignItems: 'center', justifyContent: 'space-between', height: '100%' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/')}>
              返回学习页
            </Button>
            <span style={{ fontSize: 16, fontWeight: 600 }}>
              <BarChartOutlined style={{ marginRight: 8 }} />番茄工作法统计
            </span>
          </div>
          <Segmented
            value={range}
            onChange={(value) => setRange(value as DateRange)}
            options={[
              { label: '日', value: 'day' },
              { label: '周', value: 'week' },
              { label: '月', value: 'month' },
              { label: '全部', value: 'all' },
            ]}
          />
        </div>
      </Header>

      <Content style={{ padding: 16 }}>
        <div style={{ maxWidth: 1200, margin: '0 auto' }}>
          <Row gutter={[16, 16]}>
            <Col xs={12} md={6}>
              <Card size="small"><Statistic title="累计番茄" value={cumulative.totalCount} suffix="个" /></Card>
            </Col>
            <Col xs={12} md={6}>
              <Card size="small"><Statistic title="累计时长" value={cumulative.totalHours.toFixed(1)} suffix="小时" /></Card>
            </Col>
            <Col xs={12} md={6}>
              <Card size="small"><Statistic title="日均分钟" value={cumulative.dailyAverageMinutes.toFixed(1)} suffix="分钟" /></Card>
            </Col>
            <Col xs={12} md={6}>
              <Card size="small"><Statistic title="活跃天数" value={cumulative.activeDays} suffix="天" /></Card>
            </Col>
          </Row>

          <Row gutter={[16, 16]} style={{ marginTop: 8 }}>
            <Col xs={24} lg={14}>
              <Card size="small" title="任务时长分布">
                {distribution.length === 0 ? (
                  <div style={{ textAlign: 'center', color: '#999', padding: '48px 0' }}>暂无数据，先完成一个番茄吧</div>
                ) : (
                  <ReactECharts option={pieOption} style={{ height: 320 }} />
                )}
              </Card>
            </Col>
            <Col xs={24} lg={10}>
              <Card size="small" title="本周趋势">
                <ReactECharts option={weekOption} style={{ height: 320 }} />
              </Card>
            </Col>
          </Row>
        </div>
      </Content>
    </Layout>
  )
}
