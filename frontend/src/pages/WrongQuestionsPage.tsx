import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Layout,
  Card,
  Button,
  Tag,
  List,
  Space,
  Modal,
  Input,
  Select,
  InputNumber,
  message,
  Segmented,
} from 'antd'
import { ArrowLeftOutlined, PlusOutlined, DeleteOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import {
  listWrongQuestions,
  createWrongQuestion,
  updateWrongQuestion,
  deleteWrongQuestion,
  reviewWrongQuestion,
  type WrongQuestionItem,
} from '../services/wrongQuestionApi'

const { Header, Content } = Layout
const { TextArea } = Input

type FilterType = 'all' | 'not_mastered' | 'partial' | 'mastered'

const statusColorMap: Record<string, string> = {
  not_mastered: 'red',
  partial: 'orange',
  mastered: 'green',
}

const statusTextMap: Record<string, string> = {
  not_mastered: '未掌握',
  partial: '部分掌握',
  mastered: '已掌握',
}

export function WrongQuestionsPage() {
  const navigate = useNavigate()
  const [items, setItems] = useState<WrongQuestionItem[]>([])
  const [loading, setLoading] = useState(false)
  const [filter, setFilter] = useState<FilterType>('all')

  const [createOpen, setCreateOpen] = useState(false)
  const [content, setContent] = useState('')
  const [answer, setAnswer] = useState('')
  const [explanation, setExplanation] = useState('')
  const [questionType, setQuestionType] = useState('short_answer')
  const [difficulty, setDifficulty] = useState<number>(2)

  // 复习 Modal 状态
  const [reviewItem, setReviewItem] = useState<WrongQuestionItem | null>(null)
  const [reviewLoading, setReviewLoading] = useState(false)

  const load = async () => {
    setLoading(true)
    const data = await listWrongQuestions(filter === 'all' ? undefined : { mastery_status: filter })
    setItems(data)
    setLoading(false)
  }

  useEffect(() => {
    void load()
  }, [filter])

  const stats = useMemo(() => {
    const total = items.length
    const notMastered = items.filter((i) => i.mastery_status === 'not_mastered').length
    const partial = items.filter((i) => i.mastery_status === 'partial').length
    const mastered = items.filter((i) => i.mastery_status === 'mastered').length
    return { total, notMastered, partial, mastered }
  }, [items])

  const handleCreate = async () => {
    if (!content.trim()) {
      message.warning('请输入题目内容')
      return
    }
    const created = await createWrongQuestion({
      content: content.trim(),
      answer: answer.trim() || undefined,
      explanation: explanation.trim() || undefined,
      question_type: questionType,
      difficulty,
    })
    if (!created) {
      message.error('创建错题失败')
      return
    }
    message.success('已添加到错题本')
    setCreateOpen(false)
    setContent('')
    setAnswer('')
    setExplanation('')
    setQuestionType('short_answer')
    setDifficulty(2)
    await load()
  }

  const quickSetStatus = async (id: number, status: 'not_mastered' | 'partial' | 'mastered') => {
    const updated = await updateWrongQuestion(id, { mastery_status: status, increment_review_count: true })
    if (!updated) {
      message.error('更新状态失败')
      return
    }
    message.success('状态已更新')
    await load()
  }

  const handleDelete = (id: number) => {
    Modal.confirm({
      title: '删除错题',
      content: '删除后不可恢复，确定继续吗？',
      okType: 'danger',
      onOk: async () => {
        const ok = await deleteWrongQuestion(id)
        if (!ok) {
          message.error('删除失败')
          return
        }
        message.success('已删除')
        await load()
      },
    })
  }

  const handleReview = async (item: WrongQuestionItem, quality: number) => {
    setReviewLoading(true)
    try {
      await reviewWrongQuestion(item.id, quality)
      message.success('复习记录已保存')
      setReviewItem(null)
      await load()
    } catch {
      message.error('复习记录失败，请重试')
    } finally {
      setReviewLoading(false)
    }
  }

  return (
    <Layout style={{ minHeight: '100vh', background: '#f7f8fa' }}>
      <Header style={{ background: '#fff', borderBottom: '1px solid #f0f0f0', paddingInline: 16 }}>
        <div style={{ maxWidth: 1200, margin: '0 auto', display: 'flex', height: '100%', justifyContent: 'space-between', alignItems: 'center' }}>
          <Space>
            <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/')}>返回学习页</Button>
            <span style={{ fontSize: 16, fontWeight: 600 }}>错题本</span>
          </Space>
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateOpen(true)}>新增错题</Button>
        </div>
      </Header>

      <Content style={{ padding: 16 }}>
        <div style={{ maxWidth: 1200, margin: '0 auto' }}>
          <Card size="small" style={{ marginBottom: 12 }}>
            <Space size={16} wrap>
              <Tag color="blue">总数 {stats.total}</Tag>
              <Tag color="red">未掌握 {stats.notMastered}</Tag>
              <Tag color="orange">部分掌握 {stats.partial}</Tag>
              <Tag color="green">已掌握 {stats.mastered}</Tag>
              <Segmented
                value={filter}
                onChange={(v) => setFilter(v as FilterType)}
                options={[
                  { label: '全部', value: 'all' },
                  { label: '未掌握', value: 'not_mastered' },
                  { label: '部分掌握', value: 'partial' },
                  { label: '已掌握', value: 'mastered' },
                ]}
              />
            </Space>
          </Card>

          <Card size="small" title="错题列表">
            <List
              loading={loading}
              dataSource={items}
              locale={{ emptyText: '暂无错题' }}
              renderItem={(item) => (
                <List.Item
                  actions={[
                    <Button size="small" onClick={() => quickSetStatus(item.id, 'not_mastered')}>未掌握</Button>,
                    <Button size="small" onClick={() => quickSetStatus(item.id, 'partial')}>部分掌握</Button>,
                    <Button size="small" type="primary" ghost onClick={() => quickSetStatus(item.id, 'mastered')}>已掌握</Button>,
                    <Button size="small" type="primary" onClick={() => setReviewItem(item)}>复习</Button>,
                    <Button size="small" danger icon={<DeleteOutlined />} onClick={() => handleDelete(item.id)} />,
                  ]}
                >
                  <List.Item.Meta
                    title={
                      <Space wrap>
                        <span>{item.content}</span>
                        <Tag color={statusColorMap[item.mastery_status]}>{statusTextMap[item.mastery_status]}</Tag>
                        <Tag>{item.chapter_title}</Tag>
                      </Space>
                    }
                    description={
                      <div>
                        <div>难度：{item.difficulty || '-'} · 错误次数：{item.wrong_count} · 复习次数：{item.review_count}</div>
                        <div>下次复习：{item.next_review_at ? dayjs(item.next_review_at).format('YYYY-MM-DD HH:mm') : '-'}</div>
                        {item.answer && <div>参考答案：{item.answer}</div>}
                      </div>
                    }
                  />
                </List.Item>
              )}
            />
          </Card>
        </div>
      </Content>

      <Modal
        title="新增错题"
        open={createOpen}
        onOk={handleCreate}
        onCancel={() => setCreateOpen(false)}
        okText="保存"
        cancelText="取消"
      >
        <div style={{ marginBottom: 10 }}>
          <div style={{ marginBottom: 4 }}>题目内容</div>
          <TextArea value={content} onChange={(e) => setContent(e.target.value)} autoSize={{ minRows: 3, maxRows: 6 }} />
        </div>
        <div style={{ marginBottom: 10 }}>
          <div style={{ marginBottom: 4 }}>题型</div>
          <Select
            value={questionType}
            onChange={setQuestionType}
            style={{ width: '100%' }}
            options={[
              { label: '简答题', value: 'short_answer' },
              { label: '选择题', value: 'choice' },
              { label: '填空题', value: 'fill_blank' },
              { label: '论述题', value: 'essay' },
            ]}
          />
        </div>
        <div style={{ marginBottom: 10 }}>
          <div style={{ marginBottom: 4 }}>难度</div>
          <InputNumber min={1} max={5} value={difficulty} onChange={(v) => setDifficulty(v || 2)} style={{ width: '100%' }} />
        </div>
        <div style={{ marginBottom: 10 }}>
          <div style={{ marginBottom: 4 }}>答案（可选）</div>
          <Input value={answer} onChange={(e) => setAnswer(e.target.value)} />
        </div>
        <div>
          <div style={{ marginBottom: 4 }}>解析（可选）</div>
          <TextArea value={explanation} onChange={(e) => setExplanation(e.target.value)} autoSize={{ minRows: 2, maxRows: 4 }} />
        </div>
      </Modal>

      {/* 复习评分 Modal */}
      <Modal
        open={!!reviewItem}
        title="复习评分"
        footer={null}
        onCancel={() => setReviewItem(null)}
        width={520}
      >
        {reviewItem && (
          <Space direction="vertical" style={{ width: '100%' }} size="middle">
            <Card size="small" title="题目">
              <p style={{ margin: 0 }}>{reviewItem.content}</p>
            </Card>
            <Card size="small" title="参考答案">
              <p style={{ margin: 0 }}>{reviewItem.answer || '暂无参考答案'}</p>
            </Card>
            {reviewItem.explanation && (
              <Card size="small" title="解析">
                <p style={{ margin: 0 }}>{reviewItem.explanation}</p>
              </Card>
            )}
            <div>
              <div style={{ marginBottom: 8, fontWeight: 500 }}>你的掌握程度（0 = 完全不会，5 = 完全掌握）</div>
              <Space wrap>
                {[0, 1, 2, 3, 4, 5].map((q) => (
                  <Button
                    key={q}
                    loading={reviewLoading}
                    danger={q <= 1}
                    style={q >= 4 ? { borderColor: '#52c41a', color: '#52c41a' } : q >= 2 ? { borderColor: '#fa8c16', color: '#fa8c16' } : undefined}
                    onClick={() => handleReview(reviewItem, q)}
                  >
                    {q}
                  </Button>
                ))}
              </Space>
            </div>
          </Space>
        )}
      </Modal>
    </Layout>
  )
}
