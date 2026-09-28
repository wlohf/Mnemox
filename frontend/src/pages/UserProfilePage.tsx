import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Card, Row, Col, Statistic, Tag, Button, Spin, Empty, Typography, Space, Alert, List } from 'antd'
import { UserOutlined, ReloadOutlined, BulbOutlined } from '@ant-design/icons'
import ReactECharts from 'echarts-for-react'
import { UnderstandingPanel } from '../components/UnderstandingPanel'
import { PageShell } from '../components/PageShell'
import { getProfile, refreshProfile, type UserProfile } from '../services/profileApi'

const { Text } = Typography

// 将 0~100 分映射到颜色
function scoreColor(score: number): string {
  if (score >= 75) return '#52c41a'
  if (score >= 50) return '#faad14'
  return '#ff4d4f'
}

// 时段名称
const HOUR_LABELS = Array.from({ length: 24 }, (_, i) => `${i}:00`)

export function UserProfilePage() {
  const navigate = useNavigate()
  const [profile, setProfile] = useState<UserProfile | null>(null)
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)

  const load = async () => {
    setLoading(true)
    const data = await getProfile()
    setProfile(data)
    setLoading(false)
  }

  const handleRefresh = async () => {
    setRefreshing(true)
    const data = await refreshProfile()
    if (data) setProfile(data)
    setRefreshing(false)
  }

  useEffect(() => { void load() }, [])

  const evidence = profile?.evidence_summary
  const metrics = evidence?.metrics
  const finished = metrics?.finished_count ?? 0
  const recordIndicators = [
    { label: '完成或提前完成占比', val: metrics?.completion_rate != null ? metrics.completion_rate * 100 : null },
    { label: '实际时长记录完整度', val: finished ? (metrics?.actual_duration_count ?? 0) / finished * 100 : null },
    { label: '任务关联占比', val: finished ? (finished - (evidence?.coverage.unlinked_task_count ?? finished)) / finished * 100 : null },
  ]

  // ── ECharts Options ──────────────────────────────────────────────

  const radarOption = finished > 0 ? {
    tooltip: {},
    radar: {
      indicator: recordIndicators.map(item => ({ name: item.label, max: 100 })),
      shape: 'circle',
      splitNumber: 4,
      axisName: { color: 'var(--text-secondary)', fontSize: 12 },
      splitLine: { lineStyle: { color: 'rgba(0,0,0,0.06)' } },
      splitArea: { show: false },
      axisLine: { lineStyle: { color: 'rgba(0,0,0,0.08)' } },
    },
    series: [{
      type: 'radar',
      data: [{
        value: recordIndicators.map(item => Math.round(item.val ?? 0)),
        name: '近 30 天记录概况',
        areaStyle: { color: 'rgba(99,102,241,0.15)' },
        lineStyle: { color: '#6366f1', width: 2 },
        itemStyle: { color: '#6366f1' },
      }],
    }],
  } : null

  // Use actual hourly counts, not the legacy morning/afternoon proportions.
  const timeSlotData = metrics
    ? Array.from({ length: 24 }, (_, i) => [i, 0, metrics.hour_counts[String(i)] ?? 0] as [number, number, number])
    : []

  const maxSlot = timeSlotData.length
    ? Math.max(...timeSlotData.map(d => d[2]), 1)
    : 1

  const heatmapOption = {
    tooltip: {
      formatter: (p: any) => `${HOUR_LABELS[p.data[0]]}：${p.data[2]} 条结束记录`,
    },
    grid: { top: 10, right: 16, bottom: 30, left: 46 },
    xAxis: {
      type: 'category',
      data: HOUR_LABELS,
      axisLabel: {
        interval: 2,
        color: 'var(--text-tertiary)',
        fontSize: 10,
        rotate: 45,
      },
      axisLine: { show: false },
      axisTick: { show: false },
    },
    yAxis: {
      type: 'category',
      data: [''],
      axisLabel: { show: false },
      axisLine: { show: false },
      axisTick: { show: false },
    },
    visualMap: {
      min: 0,
      max: maxSlot,
      show: false,
      inRange: { color: ['#f0f0f0', '#6366f1'] },
    },
    series: [{
      type: 'heatmap',
      data: timeSlotData,
      itemStyle: { borderRadius: 3 },
      emphasis: { itemStyle: { shadowBlur: 6, shadowColor: 'rgba(99,102,241,0.4)' } },
    }],
  }

  // ── Render ───────────────────────────────────────────────────────

  return (
    <PageShell
      title={
        <Space>
          <UserOutlined />
          学习画像
        </Space>
      }
      onBack={() => navigate('/')}
      rightExtra={
        <Button
          icon={<ReloadOutlined spin={refreshing} />}
          size="small"
          onClick={handleRefresh}
          loading={refreshing}
        >
          重新计算
        </Button>
      }
    >
      {loading ? (
        <div style={{ textAlign: 'center', padding: 80 }}>
          <Spin size="large" tip="正在加载画像..." />
        </div>
      ) : !profile ? (
        <Empty
          description="暂无学习记录，可先完成一次学习并记录实际时长"
          style={{ padding: 80 }}
        />
      ) : (
        <>
          {/* 数据不足提示 */}
          {profile.data_insufficient && (
            <Alert
              type="warning"
              showIcon
              style={{ marginBottom: 16 }}
              message="当前记录存在缺失或场景覆盖有限，以下统计不能确定稳定特性。"
            />
          )}

          {/* 洞察结论 */}
          {profile.insights && profile.insights.length > 0 && (
            <Card
              size="small"
              title={<Space><BulbOutlined style={{ color: '#f59e0b' }} /><span>记录观察</span></Space>}
              style={{ marginBottom: 16 }}
            >
              <List
                dataSource={profile.insights}
                renderItem={(insight, idx) => (
                  <List.Item style={{ padding: '8px 0', borderBottom: idx < profile.insights.length - 1 ? '1px solid var(--border-color)' : 'none' }}>
                    <Text style={{ fontSize: 13, lineHeight: 1.7 }}>• {insight}</Text>
                  </List.Item>
                )}
              />
            </Card>
          )}
          {evidence && (
            <Alert
              type="info"
              showIcon
              style={{ marginBottom: 16 }}
              message={`统计时区：${evidence.time_zone}；实际时长缺失 ${metrics?.unknown_actual_duration_count ?? 0} 条；排除 Demo、未结束或时间不明确等记录 ${evidence.coverage.excluded_all_time_count ?? evidence.coverage.excluded_record_count} 条。`}
              description="时段按结束时间归集；没有记录不等于没有学习，完成比例不代表能力，记录最多的时段不代表效率最高。"
            />
          )}
          {/* 顶部统计 */}
          <Row gutter={[12, 12]} style={{ marginBottom: 16 }}>
            <Col xs={12} sm={6}>
              <Card size="small">
                <Statistic title="已记录实际时长" value={profile.lifetime_metrics?.actual_minutes != null ? (profile.lifetime_metrics.actual_minutes / 60).toFixed(1) : '—'} suffix="小时" />
              </Card>
            </Col>
            <Col xs={12} sm={6}>
              <Card size="small">
                <Statistic title="有结束记录的天数" value={profile.total_study_days} suffix="天" />
              </Card>
            </Col>
            <Col xs={12} sm={6}>
              <Card size="small">
                <Statistic title="完成或提前完成" value={profile.total_pomodoros} suffix="个" />
              </Card>
            </Col>
            <Col xs={12} sm={6}>
              <Card size="small">
                <Statistic
                  title="连续打卡"
                  value={profile.streak_days}
                  suffix="天"
                  valueStyle={{ color: profile.streak_days >= 7 ? '#52c41a' : undefined }}
                />
              </Card>
            </Col>
          </Row>

          <Row gutter={[12, 12]}>
            {/* 雷达图 */}
            <Col xs={24} md={10}>
              <Card size="small" title="近 30 天记录概况">
                {radarOption ? (
                  <ReactECharts option={radarOption} style={{ height: 240 }} />
                ) : (
                  <Empty description="暂无数据" style={{ height: 240, display: 'flex', alignItems: 'center', justifyContent: 'center' }} />
                )}
                <Row gutter={8} style={{ marginTop: 8 }}>
                  {recordIndicators.map(({ label, val }) => (
                    <Col span={12} key={label} style={{ marginBottom: 6 }}>
                      <Text type="secondary" style={{ fontSize: 11 }}>{label}</Text>
                      <div style={{ fontWeight: 600, color: scoreColor(val ?? 0), fontSize: 14 }}>
                        {val == null ? '—' : `${Math.round(val)}%`}
                      </div>
                    </Col>
                  ))}
                </Row>
              </Card>
            </Col>

            {/* 记录分布不代表效率 */}
            <Col xs={24} md={14}>
              <Card size="small" title="近 30 天结束记录分布">
                {timeSlotData.every(d => d[2] === 0) ? (
                  <Empty description="暂无时段数据" style={{ padding: 40 }} />
                ) : (
                  <>
                    <ReactECharts option={heatmapOption} style={{ height: 100 }} />
                    {profile.optimal_hours && (
                      <div style={{ marginTop: 8 }}>
                        <Text type="secondary" style={{ fontSize: 12 }}>结束记录最多的时段：</Text>
                        <Tag color="purple" style={{ marginLeft: 6 }}>{profile.optimal_hours}</Tag>
                      </div>
                    )}
                  </>
                )}
              </Card>

              {/* 薄弱知识点 */}
              <Card size="small" title="薄弱知识点 Top 10" style={{ marginTop: 12 }}>
                {!profile.weak_points || profile.weak_points.length === 0 ? (
                  <Text type="secondary" style={{ fontSize: 12 }}>暂无数据，做错题后自动统计</Text>
                ) : (
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, padding: '4px 0' }}>
                    {profile.weak_points.map((pt, i) => (
                      <Tag
                        key={i}
                        color={i < 3 ? 'red' : i < 6 ? 'orange' : 'default'}
                        style={{ fontSize: 12 }}
                      >
                        {pt}
                      </Tag>
                    ))}
                  </div>
                )}
              </Card>
            </Col>
          </Row>

          {/* 底部：最后更新时间 */}
          {profile.last_updated && (
            <div style={{ marginTop: 12, textAlign: 'right' }}>
              <Text type="secondary" style={{ fontSize: 11 }}>
                上次更新：{new Date(profile.last_updated).toLocaleString('zh-CN')}
              </Text>
            </div>
          )}
        </>
      )}
      <UnderstandingPanel />
    </PageShell>
  )
}
