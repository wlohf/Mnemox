import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Card, Row, Col, Statistic, Tag, Button, Spin, Empty, Typography, Space, Alert, List } from 'antd'
import { UserOutlined, ReloadOutlined, BulbOutlined } from '@ant-design/icons'
import ReactECharts from 'echarts-for-react'
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

  // ── ECharts Options ──────────────────────────────────────────────

  const radarOption = profile ? {
    tooltip: {},
    radar: {
      indicator: [
        { name: '自控力', max: 100 },
        { name: '专注度', max: 100 },
        { name: '坚持度', max: 100 },
        { name: '计划执行', max: 100 },
      ],
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
        value: [
          Math.round(profile.self_control_score * 100),
          Math.round(profile.focus_score * 100),
          Math.round(profile.consistency_score * 100),
          Math.round(profile.planning_score * 100),
        ],
        name: '学习能力',
        areaStyle: { color: 'rgba(99,102,241,0.15)' },
        lineStyle: { color: '#6366f1', width: 2 },
        itemStyle: { color: '#6366f1' },
      }],
    }],
  } : null

  // 时段热力图：preferred_time_slots 是 { "0": n, "1": n, ... } 或 null
  const timeSlotData = profile?.preferred_time_slots
    ? Array.from({ length: 24 }, (_, i) => {
        const val = (profile.preferred_time_slots as Record<string, number>)[String(i)] ?? 0
        return [i, 0, val] as [number, number, number]
      })
    : []

  const maxSlot = timeSlotData.length
    ? Math.max(...timeSlotData.map(d => d[2]), 1)
    : 1

  const heatmapOption = {
    tooltip: {
      formatter: (p: any) => `${HOUR_LABELS[p.data[0]]}：${p.data[2]} 个番茄钟`,
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
          description="暂无画像数据，完成 3 个以上番茄钟后自动生成"
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
              message={`当前仅有 ${profile.total_study_days} 天的学习记录，需要至少 7 天数据才能生成准确的分析报告，以下数据仅供参考。`}
            />
          )}

          {/* 洞察结论 */}
          {profile.insights && profile.insights.length > 0 && (
            <Card
              size="small"
              title={<Space><BulbOutlined style={{ color: '#f59e0b' }} /><span>数据分析洞察</span></Space>}
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
          {/* 顶部统计 */}
          <Row gutter={[12, 12]} style={{ marginBottom: 16 }}>
            <Col xs={12} sm={6}>
              <Card size="small">
                <Statistic title="累计学习" value={profile.total_study_hours.toFixed(1)} suffix="小时" />
              </Card>
            </Col>
            <Col xs={12} sm={6}>
              <Card size="small">
                <Statistic title="学习天数" value={profile.total_study_days} suffix="天" />
              </Card>
            </Col>
            <Col xs={12} sm={6}>
              <Card size="small">
                <Statistic title="完成番茄" value={profile.total_pomodoros} suffix="个" />
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
              <Card size="small" title="学习能力雷达">
                {radarOption ? (
                  <ReactECharts option={radarOption} style={{ height: 240 }} />
                ) : (
                  <Empty description="暂无数据" style={{ height: 240, display: 'flex', alignItems: 'center', justifyContent: 'center' }} />
                )}
                <Row gutter={8} style={{ marginTop: 8 }}>
                  {[
                    { label: '自控力', val: profile.self_control_score },
                    { label: '专注度', val: profile.focus_score },
                    { label: '坚持度', val: profile.consistency_score },
                    { label: '计划执行', val: profile.planning_score },
                  ].map(({ label, val }) => (
                    <Col span={12} key={label} style={{ marginBottom: 6 }}>
                      <Text type="secondary" style={{ fontSize: 11 }}>{label}</Text>
                      <div style={{ fontWeight: 600, color: scoreColor(val * 100), fontSize: 14 }}>
                        {Math.round(val * 100)}
                      </div>
                    </Col>
                  ))}
                </Row>
              </Card>
            </Col>

            {/* 时段热力图 + 最佳时段 */}
            <Col xs={24} md={14}>
              <Card size="small" title="学习时段分布">
                {timeSlotData.every(d => d[2] === 0) ? (
                  <Empty description="暂无时段数据" style={{ padding: 40 }} />
                ) : (
                  <>
                    <ReactECharts option={heatmapOption} style={{ height: 100 }} />
                    {profile.optimal_hours && (
                      <div style={{ marginTop: 8 }}>
                        <Text type="secondary" style={{ fontSize: 12 }}>最佳学习时段：</Text>
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
    </PageShell>
  )
}
