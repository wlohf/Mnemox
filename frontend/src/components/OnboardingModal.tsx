import { Alert, Button, Card, Col, Modal, Row, Space, Statistic, Steps, Tag, Typography } from 'antd'
import {
  BookOutlined,
  CheckCircleOutlined,
  ClockCircleOutlined,
  ExperimentOutlined,
  FileTextOutlined,
  QuestionCircleOutlined,
  RocketOutlined,
} from '@ant-design/icons'
import type { OnboardingStatus } from '../services/systemApi'

const { Paragraph, Text, Title } = Typography

interface OnboardingModalProps {
  open: boolean
  status: OnboardingStatus | null
  seedLoading: boolean
  onClose: () => void
  onSeedDemo: () => Promise<void> | void
  onNavigate: (path: string) => void
  onOpenMaterials: () => void
}

const countItems = [
  { key: 'materials', label: '资料', icon: <BookOutlined /> },
  { key: 'goals', label: '目标', icon: <CheckCircleOutlined /> },
  { key: 'notes', label: '笔记', icon: <FileTextOutlined /> },
  { key: 'pomodoros', label: '番茄钟', icon: <ClockCircleOutlined /> },
]

export function OnboardingModal({
  open,
  status,
  seedLoading,
  onClose,
  onSeedDemo,
  onNavigate,
  onOpenMaterials,
}: OnboardingModalProps) {
  const counts = status?.counts || {}

  return (
    <Modal
      open={open}
      onCancel={onClose}
      width={860}
      footer={null}
      title={(
        <Space>
          <RocketOutlined style={{ color: 'var(--brand-500)' }} />
          <span>欢迎使用 Mnemox：先跑通一个学习闭环</span>
        </Space>
      )}
    >
      <Space direction="vertical" size={18} style={{ width: '100%' }}>
        <Alert
          type="info"
          showIcon
          message="费曼与苏格拉底不会做成孤立模式"
          description="它们会自然嵌入日常流程：普通提问时 AI 适度追问；每日计划里固定留下费曼复盘；写完后可用「明镜追问」让 AI 扮演小白听众继续发问。"
        />

        <Row gutter={12}>
          {countItems.map((item) => (
            <Col span={6} key={item.key}>
              <Card size="small">
                <Statistic
                  title={<Space>{item.icon}<span>{item.label}</span></Space>}
                  value={counts[item.key] || 0}
                  valueStyle={{ fontSize: 22 }}
                />
              </Card>
            </Col>
          ))}
        </Row>

        <Steps
          current={Math.min(status?.completed_steps?.length || 0, 4)}
          items={[
            {
              title: '选择起点',
              description: '导入 Demo 或上传自己的资料。',
            },
            {
              title: '执行学习',
              description: '生成计划、开番茄钟、处理复习。',
            },
            {
              title: '复盘沉淀',
              description: '用自己的话复述，转成任务/卡片。',
            },
          ]}
        />

        <Card size="small" title={status?.stage_label || '先跑通一个完整学习闭环'}>
          <Space direction="vertical" size={8} style={{ width: '100%' }}>
            <Paragraph type="secondary" style={{ marginBottom: 0 }}>
              新手阶段只关注下一步，不需要先研究所有功能。
            </Paragraph>
            {(status?.completed_steps || []).length > 0 && (
              <Space wrap>
                {status?.completed_steps?.map((step) => (
                  <Tag key={step} color="green" icon={<CheckCircleOutlined />}>{step}</Tag>
                ))}
              </Space>
            )}
          </Space>
        </Card>

        <Row gutter={16}>
          <Col span={8}>
            <Card
              title="1 分钟 Demo 模式"
              extra={<Tag color="purple">推荐首次体验</Tag>}
              style={{ height: '100%' }}
            >
              <Paragraph type="secondary">
                自动创建示例资料、目标任务、今日计划、错题、Anki 卡和学习记录，马上看到完整闭环。
              </Paragraph>
              <Button type="primary" block loading={seedLoading} onClick={() => void onSeedDemo()}>
                导入 Demo 数据
              </Button>
            </Card>
          </Col>
          <Col span={8}>
            <Card title="使用自己的资料" style={{ height: '100%' }}>
              <Paragraph type="secondary">
                上传 PDF / Word / Markdown / TXT 后，可以让 AI 生成大纲、学习目标和每日任务。
              </Paragraph>
              <Button block onClick={onOpenMaterials}>打开资料库</Button>
            </Card>
          </Col>
          <Col span={8}>
            <Card title="从今日行动开始" style={{ height: '100%' }}>
              <Paragraph type="secondary">
                已有数据时，先看今日概览和 Agent 建议，晚上在学习计划里完成费曼复盘。
              </Paragraph>
              <Space direction="vertical" style={{ width: '100%' }}>
                <Button block onClick={() => onNavigate('/dashboard')}>查看今日概览</Button>
                <Button block icon={<ExperimentOutlined />} onClick={() => onNavigate('/agent')}>查看 Agent 建议</Button>
              </Space>
            </Card>
          </Col>
        </Row>

        <Card size="small" style={{ background: 'var(--bg-tertiary)' }}>
          <Title level={5} style={{ marginTop: 0 }}>建议你按这个节奏体验</Title>
          <Space direction="vertical" size={6}>
            {(status?.suggested_next_steps || [
              '导入 Demo 数据，先体验完整学习闭环。',
              '完成一个番茄钟后，在今日计划里做费曼式复盘，再用「明镜追问」检查是否讲清楚。',
              '把复盘中讲不顺的地方交给「明镜追问」，它会像没学懂的小白一样追问。',
            ]).map((step, idx) => (
              <Text key={step}><QuestionCircleOutlined /> {idx + 1}. {step}</Text>
            ))}
          </Space>
        </Card>
      </Space>
    </Modal>
  )
}
