import { CopyOutlined } from '@ant-design/icons'
import { Button, Card, Col, Divider, List, Row, Space, Tag, Typography, message } from 'antd'
import type { WeeklyLearningReport } from '../../services/agentApi'

const { Text } = Typography

const sourceKindLabels = {
  note: '笔记',
  review: '复习',
  wrong_question: '错题',
} as const

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
  const handleCopy = async () => {
    if (!report?.consolidation.markdown) return
    try {
      if (!navigator.clipboard) throw new Error('clipboard_unavailable')
      await navigator.clipboard.writeText(report.consolidation.markdown)
      message.success('知识巩固草案已复制')
    } catch {
      message.error('无法访问剪贴板，请检查浏览器权限')
    }
  }

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
          <Divider style={{ margin: '4px 0' }} />
          <Row align="middle" justify="space-between" gutter={[12, 8]}>
            <Col>
              <Space direction="vertical" size={2}>
                <Space size={6} wrap>
                  <Text strong>知识巩固草案</Text>
                  <Tag>{report.consolidation.source_counts.total} 条来源</Tag>
                  {report.consolidation.write_policy.imported_source_count > 0 && (
                    <Tag color="gold">Obsidian 只读</Tag>
                  )}
                </Space>
                <Text type="secondary">
                  {report.consolidation.week_start} 至 {report.consolidation.week_end_exclusive}（结束日期不含）
                  · {report.time_zone}
                </Text>
              </Space>
            </Col>
            <Col>
              <Button icon={<CopyOutlined />} onClick={handleCopy}>
                复制 Markdown
              </Button>
            </Col>
          </Row>
          <List
            size="small"
            dataSource={report.consolidation.sources.slice(0, 3)}
            locale={{ emptyText: '本周暂未扫描到笔记、已完成复习或错题线索。' }}
            renderItem={(source) => (
              <List.Item>
                <Space direction="vertical" size={1}>
                  <Space size={6} wrap>
                    <Tag bordered={false}>{sourceKindLabels[source.kind]}</Tag>
                    <Text>{source.title}</Text>
                    {source.ownership !== 'mnemox' && (
                      <Text type="warning">
                        {source.ownership === 'obsidian_conflict' ? '冲突来源，只读' : '导入来源，只读'}
                      </Text>
                    )}
                  </Space>
                  {source.excerpt && <Text type="secondary">{source.excerpt}</Text>}
                </Space>
              </List.Item>
            )}
          />
          {report.consolidation.sources.length > 3 && (
            <Text type="secondary">
              另有 {report.consolidation.sources.length - 3} 条来源已写入可复制草案。
            </Text>
          )}
          {Object.values(report.consolidation.truncated).some(Boolean) && (
            <Text type="warning">
              本周来源较多，草案已按类型各保留最近 {report.consolidation.source_limit_per_kind} 条。
            </Text>
          )}
          <Text type="secondary">{report.disclaimer}</Text>
        </Space>
      ) : (
        <Text type="secondary">用你自己的学习记录整理本周重点，并只给出最多三个可选下一步。不会自动修改计划或创建任务。</Text>
      )}
    </Card>
  )
}
