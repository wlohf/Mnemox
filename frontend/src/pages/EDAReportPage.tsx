import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Card, Button, Space, Select, Statistic, Row, Col, List, Tag, message, Typography, Alert } from 'antd'
import { BarChartOutlined } from '@ant-design/icons'
import ReactECharts from 'echarts-for-react'
import { PageShell } from '../components/PageShell'
import { getEdaReport, type EDAReport } from '../services/analyticsApi'

const { Paragraph, Text } = Typography

export function EDAReportPage() {
  const navigate = useNavigate()
  const [days, setDays] = useState(30)
  const [loading, setLoading] = useState(false)
  const [report, setReport] = useState<EDAReport | null>(null)

  const load = async (d = days) => {
    setLoading(true)
    const res = await getEdaReport(d)
    if (!res) {
      message.error('加载 EDA 报告失败')
      setLoading(false)
      return
    }
    setReport(res)
    setLoading(false)
  }

  useEffect(() => {
    void load(30)
  }, [])

  const severityColor = (severity: string) => {
    if (severity === 'high') return 'red'
    if (severity === 'medium') return 'orange'
    return 'blue'
  }

  const dailyTrendOption = useMemo(() => {
    const points = report?.charts?.daily_trend || report?.daily_points || []
    return {
      tooltip: { trigger: 'axis' },
      legend: { data: ['学习分钟', '7日滚动均值'] },
      grid: { top: 36, right: 20, bottom: 42, left: 40 },
      xAxis: {
        type: 'category',
        data: points.map((p) => p.date.slice(5)),
        axisLabel: { color: '#888', fontSize: 11 },
      },
      yAxis: {
        type: 'value',
        axisLabel: { color: '#888', fontSize: 11 },
        splitLine: { lineStyle: { color: 'rgba(0,0,0,0.06)' } },
      },
      series: [
        {
          name: '学习分钟',
          type: 'line',
          smooth: true,
          symbol: 'none',
          areaStyle: { color: 'rgba(24,144,255,0.15)' },
          lineStyle: { color: '#1890ff', width: 2 },
          data: points.map((p) => p.study_minutes),
        },
        {
          name: '7日滚动均值',
          type: 'line',
          smooth: true,
          symbol: 'none',
          lineStyle: { color: '#52c41a', width: 2, type: 'dashed' },
          data: points.map((p) => p.rolling7_minutes || 0),
        },
      ],
    }
  }, [report])

  const hourlyOption = useMemo(() => {
    const data = report?.charts?.hourly_distribution || []
    return {
      tooltip: { trigger: 'axis' },
      legend: { data: ['学习分钟', '完成率(%)'] },
      grid: { top: 36, right: 20, bottom: 34, left: 40 },
      xAxis: {
        type: 'category',
        data: data.map((x) => `${x.hour}:00`),
        axisLabel: { color: '#888', fontSize: 10, interval: 2 },
      },
      yAxis: [
        { type: 'value', name: '分钟', axisLabel: { color: '#888', fontSize: 10 } },
        { type: 'value', name: '%', min: 0, max: 100, axisLabel: { color: '#888', fontSize: 10 } },
      ],
      series: [
        {
          name: '学习分钟',
          type: 'bar',
          barWidth: '60%',
          itemStyle: { color: '#722ed1', borderRadius: [4, 4, 0, 0] },
          data: data.map((x) => x.minutes),
        },
        {
          name: '完成率(%)',
          type: 'line',
          yAxisIndex: 1,
          smooth: true,
          symbol: 'none',
          lineStyle: { color: '#fa8c16', width: 2 },
          data: data.map((x) => x.completion_rate),
        },
      ],
    }
  }, [report])

  const heatmapOption = useMemo(() => {
    const heat = report?.charts?.hour_week_heatmap
    return {
      tooltip: {
        formatter: (p: any) => {
          const [hour, weekday, minutes] = p.data as [number, number, number]
          const wd = heat?.weekdays?.[weekday] || ''
          return `${wd} ${hour}:00<br/>学习时长 ${minutes} 分钟`
        },
      },
      grid: { top: 16, right: 16, bottom: 28, left: 46 },
      xAxis: {
        type: 'category',
        data: (heat?.hours || []).map((h) => `${h}`),
        axisLabel: { color: '#888', fontSize: 10, interval: 2 },
        splitArea: { show: true },
      },
      yAxis: {
        type: 'category',
        data: heat?.weekdays || [],
        axisLabel: { color: '#888', fontSize: 11 },
        splitArea: { show: true },
      },
      visualMap: {
        min: 0,
        max: Math.max(1, ...(heat?.points || []).map((p) => p[2] || 0)),
        calculable: true,
        orient: 'horizontal',
        left: 'center',
        bottom: 0,
        inRange: { color: ['#f5f5f5', '#91d5ff', '#1890ff'] },
      },
      series: [{
        type: 'heatmap',
        data: heat?.points || [],
        label: { show: false },
      }],
    }
  }, [report])

  const stopReasonOption = useMemo(() => {
    const data = report?.charts?.stop_reason_distribution || []
    return {
      tooltip: { trigger: 'item' },
      legend: { bottom: 0 },
      series: [{
        type: 'pie',
        radius: ['45%', '72%'],
        center: ['50%', '45%'],
        data: data.map((d) => ({ name: d.reason, value: d.count })),
        label: { formatter: '{b}: {d}%' },
      }],
    }
  }, [report])

  const durationBucketOption = useMemo(() => {
    const data = report?.charts?.duration_bucket_distribution || []
    return {
      tooltip: { trigger: 'axis' },
      grid: { top: 20, right: 16, bottom: 30, left: 36 },
      xAxis: {
        type: 'category',
        data: data.map((d) => d.bucket),
        axisLabel: { color: '#888', fontSize: 11 },
      },
      yAxis: {
        type: 'value',
        axisLabel: { color: '#888', fontSize: 11 },
      },
      series: [{
        type: 'bar',
        data: data.map((d) => d.count),
        barWidth: '55%',
        itemStyle: { color: '#13c2c2', borderRadius: [4, 4, 0, 0] },
      }],
    }
  }, [report])

  const personaRadarOption = useMemo(() => {
    const completion = report?.summary?.completion_rate || 0
    const activeRatio = report?.period_days ? ((report?.summary?.active_days || 0) / report.period_days) * 100 : 0
    const avgDaily = Math.min(100, ((report?.summary?.avg_daily_minutes || 0) / 2))
    const antiDistract = Math.max(
      0,
      100 - (((report?.summary?.stop_reason_counts?.distracted || 0) / Math.max(1, report?.summary?.pomodoro_count || 1)) * 100),
    )
    const execution = report?.summary?.total_tasks
      ? ((report.summary.completed_tasks / Math.max(1, report.summary.total_tasks)) * 100)
      : 0

    return {
      tooltip: {},
      radar: {
        indicator: [
          { name: '专注完成', max: 100 },
          { name: '活跃连续性', max: 100 },
          { name: '时长投入', max: 100 },
          { name: '抗干扰', max: 100 },
          { name: '任务执行', max: 100 },
        ],
        splitNumber: 4,
      },
      series: [{
        type: 'radar',
        data: [{
          value: [completion, activeRatio, avgDaily, antiDistract, execution].map((x) => Number(x.toFixed(1))),
          name: report?.profile?.profile_type || '用户画像',
          areaStyle: { color: 'rgba(82,196,26,0.18)' },
          lineStyle: { color: '#52c41a', width: 2 },
          itemStyle: { color: '#52c41a' },
        }],
      }],
    }
  }, [report])

  return (
    <PageShell
      title={<><BarChartOutlined style={{ marginRight: 8 }} />学习行为 EDA 报告</>}
      onBack={() => navigate('/')}
      rightExtra={(
        <Space>
          <Select
            value={days}
            style={{ width: 120 }}
            options={[
              { label: '最近7天', value: 7 },
              { label: '最近30天', value: 30 },
              { label: '最近90天', value: 90 },
            ]}
            onChange={(val) => {
              setDays(val)
              void load(val)
            }}
          />
          <Button loading={loading} onClick={() => void load(days)}>刷新</Button>
        </Space>
      )}
    >
      <Row gutter={[12, 12]}>
        <Col xs={12} md={6}><Card size="small"><Statistic title="总学习时长(分钟)" value={report?.summary.total_minutes || 0} /></Card></Col>
        <Col xs={12} md={6}><Card size="small"><Statistic title="日均学习(分钟)" value={report?.summary.avg_daily_minutes || 0} /></Card></Col>
        <Col xs={12} md={6}><Card size="small"><Statistic title="番茄完成率" value={report?.summary.completion_rate || 0} suffix="%" /></Card></Col>
        <Col xs={12} md={6}><Card size="small"><Statistic title="任务完成" value={`${report?.summary.completed_tasks || 0}/${report?.summary.total_tasks || 0}`} /></Card></Col>
      </Row>

      {!!report?.profile && (
        <Alert
          style={{ marginTop: 12 }}
          type="info"
          showIcon
          message={`学习画像：${report.profile.profile_type}（置信度 ${(report.profile.confidence * 100).toFixed(1)}%）`}
          description={(
            <div>
              <div>最佳学习窗口：{report.profile.best_study_window}</div>
              <div style={{ marginTop: 4 }}>
                证据：{(report.profile.evidence || []).join('；')}
              </div>
            </div>
          )}
        />
      )}

      <Row gutter={[12, 12]} style={{ marginTop: 0 }}>
        <Col xs={24} lg={12}>
          <Card size="small" title="图1：学习趋势（含7日滚动均值）" style={{ marginTop: 12 }}>
            <ReactECharts option={dailyTrendOption} style={{ height: 280 }} opts={{ renderer: 'svg' }} />
          </Card>
        </Col>
        <Col xs={24} lg={12}>
          <Card size="small" title="图2：时段效率分布（分钟 + 完成率）" style={{ marginTop: 12 }}>
            <ReactECharts option={hourlyOption} style={{ height: 280 }} opts={{ renderer: 'svg' }} />
          </Card>
        </Col>
      </Row>

      <Row gutter={[12, 12]}>
        <Col xs={24} lg={14}>
          <Card size="small" title="图3：周内 × 小时热力图" style={{ marginTop: 12 }}>
            <ReactECharts option={heatmapOption} style={{ height: 320 }} opts={{ renderer: 'svg' }} />
          </Card>
        </Col>
        <Col xs={24} lg={10}>
          <Card size="small" title="图4：停止原因占比" style={{ marginTop: 12 }}>
            <ReactECharts option={stopReasonOption} style={{ height: 320 }} opts={{ renderer: 'svg' }} />
          </Card>
        </Col>
      </Row>

      <Row gutter={[12, 12]}>
        <Col xs={24} lg={12}>
          <Card size="small" title="图5：单次专注时长分桶" style={{ marginTop: 12 }}>
            <ReactECharts option={durationBucketOption} style={{ height: 260 }} opts={{ renderer: 'svg' }} />
          </Card>
        </Col>
        <Col xs={24} lg={12}>
          <Card size="small" title="图6：学习能力雷达" style={{ marginTop: 12 }}>
            <ReactECharts option={personaRadarOption} style={{ height: 260 }} opts={{ renderer: 'svg' }} />
          </Card>
        </Col>
      </Row>

      <Card size="small" title="图表解读" style={{ marginTop: 12 }}>
        <List
          dataSource={report?.chart_analysis || []}
          renderItem={(item) => <List.Item>• <Text>{item}</Text></List.Item>}
        />
      </Card>

      <Card size="small" title="关键洞察" style={{ marginTop: 12 }} loading={loading}>
        <List
          dataSource={report?.insights || []}
          locale={{ emptyText: '暂无明显异常，继续保持！' }}
          renderItem={(item) => (
            <List.Item>
              <Space direction="vertical" size={4} style={{ width: '100%' }}>
                <Space>
                  <Tag color={severityColor(item.severity)}>{item.severity}</Tag>
                  <strong>{item.title}</strong>
                </Space>
                <Paragraph style={{ marginBottom: 0 }}>{item.detail}</Paragraph>
              </Space>
            </List.Item>
          )}
        />
      </Card>

      <Card size="small" title="建议动作" style={{ marginTop: 12 }}>
        <List
          dataSource={report?.recommendations || []}
          renderItem={(item) => <List.Item>• {item}</List.Item>}
        />
      </Card>

      <Card size="small" title="报告文本（可复制）" style={{ marginTop: 12 }}>
        <Paragraph copyable={{ text: report?.markdown || '' }} style={{ whiteSpace: 'pre-wrap', marginBottom: 0 }}>
          {report?.markdown || '暂无数据'}
        </Paragraph>
      </Card>
    </PageShell>
  )
}
