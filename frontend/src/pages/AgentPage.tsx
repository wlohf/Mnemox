import { useEffect, useState } from 'react'
import { Button, Card, Col, Empty, Input, List, Row, Space, Spin, Tag, Typography, message } from 'antd'
import { ArrowLeftOutlined, RobotOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { listAgents, runAgent, type AgentInfo } from '../services/agentApi'

const { Paragraph, Text, Title } = Typography

export function AgentPage() {
  const navigate = useNavigate()
  const [agents, setAgents] = useState<AgentInfo[]>([])
  const [selected, setSelected] = useState('study_plan')
  const [messageText, setMessageText] = useState('')
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<any>(null)

  useEffect(() => {
    void (async () => {
      const data = await listAgents()
      setAgents(data)
      if (data.length && !data.some((item) => item.name === selected)) {
        setSelected(data[0].name)
      }
    })()
  }, [])

  const handleRun = async () => {
    setLoading(true)
    try {
      const payload = selected === 'chat' ? { message: messageText } : {}
      const response = await runAgent(selected, payload)
      if (!response) {
        message.error('Agent 执行失败')
        return
      }
      setResult(response.result)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={{ maxWidth: 1080, margin: '0 auto', padding: '24px 16px' }}>
      <Space style={{ marginBottom: 16 }}>
        <Button size="small" icon={<ArrowLeftOutlined />} onClick={() => navigate('/')}>返回主页</Button>
        <RobotOutlined style={{ color: 'var(--accent-600)', fontSize: 20 }} />
        <Title level={4} style={{ margin: 0 }}>Agent 工作台</Title>
      </Space>

      <Row gutter={[16, 16]}>
        <Col xs={24} md={8}>
          <Card title="可用 Agent" size="small">
            {agents.length === 0 ? <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} /> : (
              <List
                dataSource={agents}
                renderItem={(agent) => (
                  <List.Item
                    onClick={() => { setSelected(agent.name); setResult(null) }}
                    style={{ cursor: 'pointer', background: selected === agent.name ? 'var(--accent-50)' : undefined, padding: 12, borderRadius: 8 }}
                  >
                    <List.Item.Meta
                      title={<Space><Text strong>{agent.name}</Text>{selected === agent.name && <Tag color="blue">当前</Tag>}</Space>}
                      description={agent.description}
                    />
                  </List.Item>
                )}
              />
            )}
          </Card>
        </Col>

        <Col xs={24} md={16}>
          <Card
            title={`运行：${selected}`}
            extra={<Button type="primary" loading={loading} onClick={handleRun}>执行</Button>}
          >
            {selected === 'chat' && (
              <Input.TextArea
                value={messageText}
                onChange={(event) => setMessageText(event.target.value)}
                rows={4}
                placeholder="输入想让学习助手解释或追问的问题"
                style={{ marginBottom: 16 }}
              />
            )}

            {loading ? <Spin /> : result ? (
              <div>
                {result.reply && <Paragraph style={{ whiteSpace: 'pre-wrap' }}>{result.reply}</Paragraph>}
                {result.summary && <Paragraph strong>{result.summary}</Paragraph>}
                {Array.isArray(result.actions) && result.actions.length > 0 && (
                  <List size="small" header="建议行动" dataSource={result.actions} renderItem={(item: string) => <List.Item>{item}</List.Item>} />
                )}
                {Array.isArray(result.items) && result.items.length > 0 && (
                  <List
                    size="small"
                    header="条目"
                    dataSource={result.items}
                    renderItem={(item: any) => <List.Item><pre style={{ margin: 0, whiteSpace: 'pre-wrap' }}>{JSON.stringify(item, null, 2)}</pre></List.Item>}
                  />
                )}
                {!result.reply && !result.summary && <pre style={{ whiteSpace: 'pre-wrap' }}>{JSON.stringify(result, null, 2)}</pre>}
              </div>
            ) : (
              <Empty description="选择 Agent 后点击执行" />
            )}
          </Card>
        </Col>
      </Row>
    </div>
  )
}
