import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Card, Button, Space, Tag, List, Typography, message } from 'antd'
import { NotificationOutlined } from '@ant-design/icons'
import { PageShell } from '../components/PageShell'
import {
  getDailyIntervention,
  generateDailyIntervention,
  type DailyInterventionReport,
} from '../services/interventionApi'

const { Paragraph } = Typography

export function InterventionPage() {
  const navigate = useNavigate()
  const [loading, setLoading] = useState(false)
  const [generating, setGenerating] = useState(false)
  const [report, setReport] = useState<DailyInterventionReport | null>(null)

  const load = async () => {
    setLoading(true)
    let res = await getDailyIntervention()
    if (!res) {
      // 无今日报告，自动生成
      res = await generateDailyIntervention()
      if (!res) {
        message.error('加载主动干预报告失败')
        setLoading(false)
        return
      }
    }
    setReport(res)
    setLoading(false)
  }

  useEffect(() => {
    void load()
  }, [])

  const riskColor = report?.risk_level === 'high' ? 'red' : report?.risk_level === 'medium' ? 'orange' : 'green'

  return (
    <PageShell
      title={<><NotificationOutlined style={{ marginRight: 8 }} />AI 主动干预</>}
      onBack={() => navigate('/')}
      rightExtra={(
        <Space>
          <Button loading={loading} onClick={() => void load()}>刷新</Button>
          <Button
            type="primary"
            loading={generating}
            onClick={async () => {
              setGenerating(true)
              const generated = await generateDailyIntervention()
              if (!generated) {
                message.error('生成 AI 干预报告失败')
                setGenerating(false)
                return
              }
              setReport(generated)
              setGenerating(false)
              message.success('已生成今日 AI 主动干预报告')
            }}
          >
            生成今日报告
          </Button>
        </Space>
      )}
    >
      <Card size="small" loading={loading}>
        <Space direction="vertical" size={8} style={{ width: '100%' }}>
          <Space>
            <Tag color={riskColor}>风险等级：{report?.risk_level || '-'}</Tag>
            {report?.should_push ? <Tag color="gold">建议推送</Tag> : <Tag>无需推送</Tag>}
          </Space>
          <Paragraph style={{ marginBottom: 0 }}><strong>{report?.push_title || '暂无标题'}</strong></Paragraph>
          <Paragraph style={{ marginBottom: 0 }}>{report?.push_body || '暂无正文'}</Paragraph>
          <Paragraph type="secondary" style={{ marginBottom: 0 }}>{report?.summary || '暂无总结'}</Paragraph>
        </Space>
      </Card>

      <Card size="small" title="关键数据" style={{ marginTop: 12 }}>
        <List
          dataSource={report?.highlights || []}
          renderItem={(item) => <List.Item>• {item}</List.Item>}
        />
      </Card>

      <Card size="small" title="建议动作" style={{ marginTop: 12 }}>
        <List
          dataSource={report?.suggestions || []}
          renderItem={(item) => <List.Item>• {item}</List.Item>}
        />
      </Card>
    </PageShell>
  )
}
