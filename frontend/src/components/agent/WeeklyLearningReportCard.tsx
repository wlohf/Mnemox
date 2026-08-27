import { Button, Card, Col, List, Row, Space, Typography } from 'antd'
import type { WeeklyLearningReport } from '../../services/agentApi'

const { Text } = Typography

interface WeeklyLearningReportCardProps {
  report: WeeklyLearningReport | null
  loading: boolean
  onGenerate: () => void
  onNavigate: (route: string) => void
}

/** A read-only review with navigation-only next steps. */
export function WeeklyLearningReportCard({
  report,
  loading,
  onGenerate,
  onNavigate,
}: WeeklyLearningReportCardProps) {
  return (
    <Card
      size="small"
      title="本周复盘"
      extra={<Button size="small" loading={loading} onClick={onGenerate}>生成复盘</Button>}
    >
      {report ? (
        <Space direction="vertical" size={10} style={{ width: '100%' }}>
          <Text strong>{report.headline}</Text>
          <Row gutter={[16, 12]}>
            <Col xs={24} md={8}>
              <Text type="secondary">做得不错</Text>
              <List size="small" dataSource={report.wins} renderItem={(item) => <List.Item>{item}</List.Item>} />
            </Col>
            <Col xs={24} md={8}>
              <Text type="secondary">值得留意</Text>
              <List
                size="small"
                dataSource={report.attention}
                locale={{ emptyText: '目前没有需要紧急处理的积压。' }}
                renderItem={(item) => <List.Item>{item}</List.Item>}
              />
            </Col>
            <Col xs={24} md={8}>
              <Text type="secondary">下周先做什么</Text>
              <List
                size="small"
                dataSource={report.next_steps}
                renderItem={(item) => (
                  <List.Item actions={[
                    <Button key={item.title} size="small" type="primary" onClick={() => onNavigate(item.route)}>
                      去做
                    </Button>,
                  ]}>
                    <Space direction="vertical" size={1}>
                      <Text>{item.title}</Text>
                      <Text type="secondary">{item.estimated_minutes} 分钟 · {item.reason}</Text>
                    </Space>
                  </List.Item>
                )}
              />
            </Col>
          </Row>
          <Text type="secondary">{report.disclaimer}</Text>
        </Space>
      ) : (
        <Text type="secondary">用你自己的学习记录整理本周重点，并只给出最多三个可选下一步。不会自动修改计划或创建任务。</Text>
      )}
    </Card>
  )
}
