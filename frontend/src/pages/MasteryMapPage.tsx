import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Layout, Card, Button, List, Progress, Space, Tag, Row, Col, message } from 'antd'
import { ArrowLeftOutlined, HeatMapOutlined } from '@ant-design/icons'
import { getMasteryMap, type MasteryMapData } from '../services/learningApi'
import { getApiErrorMessage } from '../services/apiClient'

const { Header, Content } = Layout

export function MasteryMapPage() {
  const navigate = useNavigate()
  const [data, setData] = useState<MasteryMapData | null>(null)

  const load = async () => {
    try {
      const d = await getMasteryMap()
      setData(d)
    } catch (error) {
      message.error(getApiErrorMessage(error, '加载掌握度地图失败'))
    }
  }

  useEffect(() => {
    void load()
  }, [])

  const overall = useMemo(() => {
    const all = (data?.materials || []).flatMap((m) => m.chapters)
    if (all.length === 0) return 0
    return Math.round(all.reduce((s, c) => s + c.mastery_level, 0) / all.length)
  }, [data])

  return (
    <Layout style={{ minHeight: '100vh', background: 'var(--bg-base)' }}>
      <Header style={{ background: 'var(--bg-surface)', borderBottom: '1px solid var(--border-light)', paddingInline: 16 }}>
        <div style={{ maxWidth: 1200, margin: '0 auto', display: 'flex', justifyContent: 'space-between', alignItems: 'center', height: '100%' }}>
          <Space>
            <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/')}>返回学习页</Button>
            <span style={{ fontSize: 16, fontWeight: 600 }}><HeatMapOutlined style={{ marginRight: 8 }} />掌握度地图</span>
          </Space>
          <Button onClick={() => void load()}>刷新</Button>
        </div>
      </Header>

      <Content style={{ padding: 16 }}>
        <div style={{ maxWidth: 1200, margin: '0 auto' }}>
          <Card size="small" title="总体掌握度" style={{ marginBottom: 12 }}>
            <Progress percent={overall} strokeColor={overall < 50 ? '#ef4444' : overall < 80 ? '#f59e0b' : '#10b981'} />
          </Card>

          <Row gutter={[16, 16]}>
            <Col xs={24} lg={16}>
              <Card size="small" title="资料掌握分布">
                <List
                  dataSource={data?.materials || []}
                  locale={{ emptyText: '暂无章节数据' }}
                  renderItem={(m) => (
                    <List.Item>
                      <div style={{ width: '100%' }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6 }}>
                          <span>{m.material_title}</span>
                          <Tag>{m.average_mastery}%</Tag>
                        </div>
                        <Progress percent={Math.round(m.average_mastery)} />
                      </div>
                    </List.Item>
                  )}
                />
              </Card>
            </Col>
            <Col xs={24} lg={8}>
              <Card size="small" title="薄弱点（优先复习）">
                <List
                  dataSource={data?.weak_points || []}
                  locale={{ emptyText: '暂无明显薄弱点' }}
                  renderItem={(w) => (
                    <List.Item>
                      <div>
                        <div style={{ fontSize: 13 }}>{w.chapter_title}</div>
                        <div style={{ fontSize: 12, color: '#999' }}>{w.material_title} · {Math.round(w.mastery_level)}%</div>
                      </div>
                    </List.Item>
                  )}
                />
              </Card>
            </Col>
          </Row>
        </div>
      </Content>
    </Layout>
  )
}
