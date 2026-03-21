import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Card, Row, Col, Statistic, List, Button, Tag, Space } from 'antd'
import { DashboardOutlined } from '@ant-design/icons'
import { getDashboard, type DashboardData } from '../services/learningApi'
import { PageShell } from '../components/PageShell'

export function DashboardPage() {
  const navigate = useNavigate()
  const [data, setData] = useState<DashboardData | null>(null)

  const load = async () => {
    const d = await getDashboard()
    setData(d)
  }

  useEffect(() => {
    void load()
  }, [])

  return (
    <PageShell
      title={<><DashboardOutlined style={{ marginRight: 8 }} />今日驾驶舱</>}
      onBack={() => navigate('/')}
      rightExtra={<Button onClick={() => void load()}>刷新</Button>}
    >
      <Row gutter={[16, 16]}>
        <Col xs={12} md={6}><Card size="small"><Statistic title="今日任务" value={data?.today_task_count || 0} /></Card></Col>
        <Col xs={12} md={6}><Card size="small"><Statistic title="待完成" value={data?.today_pending_count || 0} /></Card></Col>
        <Col xs={12} md={6}><Card size="small"><Statistic title="到期复习" value={data?.due_review_count || 0} /></Card></Col>
        <Col xs={12} md={6}><Card size="small"><Statistic title="学习分钟" value={data?.today_study_minutes || 0} /></Card></Col>
      </Row>

      <Row gutter={[16, 16]} style={{ marginTop: 8 }}>
        <Col xs={24} lg={12}>
          <Card size="small" title="今日最该做的事">
            <List
              dataSource={data?.recommended_actions || []}
              locale={{ emptyText: '暂无推荐动作' }}
              renderItem={(a) => (
                <List.Item>
                  <Space>
                    <Tag color={a.type === 'review' ? 'orange' : 'blue'}>{a.type === 'review' ? '复习' : '任务'}</Tag>
                    <span>{a.title}</span>
                  </Space>
                </List.Item>
              )}
            />
          </Card>
        </Col>
        <Col xs={24} lg={12}>
          <Card size="small" title="今日任务清单">
            <List
              dataSource={data?.today_tasks || []}
              locale={{ emptyText: '今天暂无任务' }}
              renderItem={(t) => (
                <List.Item>
                  <Space>
                    <Tag>{t.task_type || 'learn'}</Tag>
                    <span>{t.title}</span>
                    <Tag color={t.status === 'completed' ? 'green' : t.status === 'in_progress' ? 'orange' : 'default'}>{t.status}</Tag>
                  </Space>
                </List.Item>
              )}
            />
          </Card>
        </Col>
      </Row>
    </PageShell>
  )
}
