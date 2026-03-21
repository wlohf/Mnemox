import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Card, Button, List, Space, message, Tag, Segmented, Radio, Input, Spin, Alert } from 'antd'
import { CheckCircleOutlined, ArrowRightOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import { listReviewTasks, completeReviewTask, type ReviewTaskItem } from '../services/reviewApi'
import { apiFetch } from '../services/apiClient'
import { PageShell } from '../components/PageShell'

interface ReviewContent {
  summary: string[]
  questions: Array<{
    id: number
    type: 'choice' | 'short_answer'
    question: string
    options?: string[]
    correct_answer?: string
    reference_answer?: string
  }>
}

interface ReviewResult {
  score: number
  quality: number
  feedback: string
  next_review_date: string
}

type ReviewStep = 'list' | 'summary' | 'questions' | 'result'

export function ReviewPage() {
  const navigate = useNavigate()
  const [items, setItems] = useState<ReviewTaskItem[]>([])
  const [loading, setLoading] = useState(false)
  const [scope, setScope] = useState<'due' | 'all'>('due')
  const [itemType, setItemType] = useState<'all' | 'question' | 'chapter'>('all')

  // AI Review flow state
  const [currentStep, setCurrentStep] = useState<ReviewStep>('list')
  const [selectedTask, setSelectedTask] = useState<ReviewTaskItem | null>(null)
  const [reviewContent, setReviewContent] = useState<ReviewContent | null>(null)
  const [userAnswers, setUserAnswers] = useState<Record<number, string>>({})
  const [reviewResult, setReviewResult] = useState<ReviewResult | null>(null)
  const [submitting, setSubmitting] = useState(false)

  const load = async () => {
    setLoading(true)
    const data = await listReviewTasks(scope, itemType)
    setItems(data)
    setLoading(false)
  }

  useEffect(() => {
    void load()
  }, [scope, itemType])

  const startReview = async (task: ReviewTaskItem) => {
    if (task.item_type === 'question') {
      // 错题复习：直接进入评分卡，无需 AI 生成题目
      setSelectedTask(task)
      setCurrentStep('questions')
      setReviewContent(null)
      setUserAnswers({})
      setReviewResult(null)
      return
    }

    setSelectedTask(task)
    setCurrentStep('summary')
    setLoading(true)

    try {
      const content = await apiFetch<ReviewContent>(`/api/review/${task.task_id}/content`)
      setReviewContent(content)
      setUserAnswers({})
      setReviewResult(null)
    } catch (error: any) {
      message.error(error.message || '加载复习内容失败')
      setCurrentStep('list')
    } finally {
      setLoading(false)
    }
  }

  const submitAnswers = async () => {
    if (!selectedTask || !reviewContent) return

    const answers = reviewContent.questions.map((q) => ({
      question: q.question,
      answer: userAnswers[q.id] || '',
    }))

    setSubmitting(true)
    try {
      const result = await apiFetch<ReviewResult>(`/api/review/${selectedTask.task_id}/submit`, {
        method: 'POST',
        body: JSON.stringify({ answers }),
      })
      setReviewResult(result)
      setCurrentStep('result')
      message.success('复习评估完成')
    } catch (error: any) {
      message.error(error.message || '提交答案失败')
    } finally {
      setSubmitting(false)
    }
  }

  const resetReview = () => {
    setCurrentStep('list')
    setSelectedTask(null)
    setReviewContent(null)
    setUserAnswers({})
    setReviewResult(null)
    void load()
  }

  // Render list view
  if (currentStep === 'list') {
    return (
      <PageShell
        title={
          <>
            复习中心
            <Segmented
              size="small"
              value={scope}
              onChange={(v) => setScope(v as 'due' | 'all')}
              options={[
                { label: '仅到期', value: 'due' },
                { label: '全部任务', value: 'all' },
              ]}
              style={{ marginLeft: 12 }}
            />
            <Segmented
              size="small"
              value={itemType}
              onChange={(v) => setItemType(v as 'all' | 'question' | 'chapter')}
              options={[
                { label: '全部类型', value: 'all' },
                { label: '错题', value: 'question' },
                { label: '章节', value: 'chapter' },
              ]}
              style={{ marginLeft: 8 }}
            />
          </>
        }
        onBack={() => navigate('/')}
        rightExtra={<Tag color="blue">任务 {items.length}</Tag>}
      >
        <Card size="small" title={scope === 'due' ? '到期复习任务' : '全部复习任务'}>
          <List
            loading={loading}
            dataSource={items}
            locale={{ emptyText: scope === 'due' ? '暂无到期复习任务' : '暂无复习任务' }}
            renderItem={(item) => (
              <List.Item
                actions={[
                  <Button
                    key={`start-${item.task_id}`}
                    type="primary"
                    icon={<ArrowRightOutlined />}
                    onClick={() => startReview(item)}
                    disabled={item.item_type !== 'chapter'}
                  >
                    {item.item_type === 'chapter' ? '开始AI复习' : '暂不支持'}
                  </Button>,
                ]}
              >
                <List.Item.Meta
                  title={
                    <Space>
                      <span>{item.content}</span>
                      <Tag color={item.item_type === 'chapter' ? 'blue' : 'purple'}>
                        {item.item_type === 'chapter' ? '章节复习' : '错题复习'}
                      </Tag>
                    </Space>
                  }
                  description={
                    <div>
                      <div>章节：{item.chapter_title} · 当前状态：{item.mastery_status}</div>
                      {item.item_type === 'question' ? (
                        <>
                          <div>上次错题时间：{item.last_wrong_at ? dayjs(item.last_wrong_at).format('YYYY-MM-DD HH:mm') : '-'}</div>
                          <div>下次复习：{item.next_review_at ? dayjs(item.next_review_at).format('YYYY-MM-DD HH:mm') : '-'}</div>
                        </>
                      ) : (
                        <>
                          <div>章节掌握度：{Math.round(item.chapter_mastery_level || 0)}%</div>
                          <div>任务计划时间：{item.scheduled_date ? dayjs(item.scheduled_date).format('YYYY-MM-DD HH:mm') : '-'}</div>
                        </>
                      )}
                    </div>
                  }
                />
              </List.Item>
            )}
          />
        </Card>
      </PageShell>
    )
  }

  // Render summary view
  if (currentStep === 'summary') {
    return (
      <PageShell
        title={`复习：${selectedTask?.content || ''}`}
        onBack={resetReview}
      >
        <Spin spinning={loading}>
          <Card
            size="small"
            title="📚 知识点总结"
            extra={
              <Button type="primary" onClick={() => setCurrentStep('questions')}>
                开始答题
              </Button>
            }
          >
            {reviewContent && reviewContent.summary.length > 0 ? (
              <List
                dataSource={reviewContent.summary}
                renderItem={(point, idx) => (
                  <List.Item>
                    <Space>
                      <Tag color="blue">{idx + 1}</Tag>
                      <span>{point}</span>
                    </Space>
                  </List.Item>
                )}
              />
            ) : (
              <Alert message="正在生成知识点总结..." type="info" />
            )}
          </Card>
        </Spin>
      </PageShell>
    )
  }

  // Render questions view
  if (currentStep === 'questions') {
    // 错题直接评分卡（item_type === 'question'）
    if (selectedTask?.item_type === 'question') {
      return (
        <PageShell
          title={`复习错题：${selectedTask.content || ''}`}
          onBack={resetReview}
        >
          <Space direction="vertical" style={{ width: '100%' }} size="middle">
            <Card size="small" title="题目">
              <p style={{ margin: 0 }}>{selectedTask.content}</p>
            </Card>
            <Card size="small" title="当前掌握状态">
              <Tag color={selectedTask.mastery_status === 'mastered' ? 'green' : selectedTask.mastery_status === 'partial' ? 'orange' : 'red'}>
                {selectedTask.mastery_status === 'mastered' ? '已掌握' : selectedTask.mastery_status === 'partial' ? '部分掌握' : '未掌握'}
              </Tag>
            </Card>
            <Card size="small" title="自我评分">
              <div style={{ marginBottom: 8 }}>回忆答案后，评估你的掌握程度（0 = 完全不会，5 = 完全掌握）</div>
              <Space wrap>
                {[0, 1, 2, 3, 4, 5].map((q) => (
                  <Button
                    key={q}
                    loading={submitting}
                    danger={q <= 1}
                    style={q >= 4 ? { borderColor: '#52c41a', color: '#52c41a' } : q >= 2 ? { borderColor: '#fa8c16', color: '#fa8c16' } : undefined}
                    onClick={async () => {
                      setSubmitting(true)
                      try {
                        await completeReviewTask(selectedTask.task_id, q)
                        message.success('复习记录已保存')
                        resetReview()
                      } catch {
                        message.error('保存失败，请重试')
                      } finally {
                        setSubmitting(false)
                      }
                    }}
                  >
                    {q}
                  </Button>
                ))}
              </Space>
            </Card>
          </Space>
        </PageShell>
      )
    }

    const allAnswered = reviewContent?.questions.every((q) => userAnswers[q.id]?.trim())

    return (
      <PageShell
        title={`复习：${selectedTask?.content || ''}`}
        onBack={() => setCurrentStep('summary')}
      >
        <Card
          size="small"
          title="✍️ 检验题目"
          extra={
            <Button
              type="primary"
              icon={<CheckCircleOutlined />}
              onClick={submitAnswers}
              loading={submitting}
              disabled={!allAnswered}
            >
              提交答案
            </Button>
          }
        >
          <Space direction="vertical" style={{ width: '100%' }} size="large">
            {reviewContent?.questions.map((q, idx) => (
              <Card key={q.id} size="small" title={`题目 ${idx + 1}`}>
                <div style={{ marginBottom: 12, fontSize: 15 }}>{q.question}</div>

                {q.type === 'choice' && q.options ? (
                  <Radio.Group
                    value={userAnswers[q.id]}
                    onChange={(e) => setUserAnswers((prev) => ({ ...prev, [q.id]: e.target.value }))}
                    style={{ width: '100%' }}
                  >
                    <Space direction="vertical" style={{ width: '100%' }}>
                      {q.options.map((opt) => (
                        <Radio key={opt} value={opt.charAt(0)}>
                          {opt}
                        </Radio>
                      ))}
                    </Space>
                  </Radio.Group>
                ) : (
                  <Input.TextArea
                    value={userAnswers[q.id] || ''}
                    onChange={(e) => setUserAnswers((prev) => ({ ...prev, [q.id]: e.target.value }))}
                    placeholder="请输入你的答案"
                    autoSize={{ minRows: 3, maxRows: 8 }}
                  />
                )}
              </Card>
            ))}
          </Space>
        </Card>
      </PageShell>
    )
  }

  // Render result view
  if (currentStep === 'result' && reviewResult) {
    const scoreColor = reviewResult.score >= 80 ? 'green' : reviewResult.score >= 60 ? 'orange' : 'red'

    return (
      <PageShell
        title={`复习：${selectedTask?.content || ''}`}
        onBack={resetReview}
      >
        <Card size="small" title="📊 评估结果">
          <Space direction="vertical" style={{ width: '100%' }} size="large">
            <Card size="small">
              <div style={{ textAlign: 'center' }}>
                <div style={{ fontSize: 48, fontWeight: 'bold', color: `var(--${scoreColor})` }}>
                  {reviewResult.score}
                </div>
                <div style={{ fontSize: 16, color: 'var(--text-secondary)' }}>综合得分</div>
              </div>
            </Card>

            <Card size="small" title="反馈">
              <p>{reviewResult.feedback}</p>
            </Card>

            <Card size="small" title="复习计划">
              <p>
                掌握度评级：<Tag color="blue">{reviewResult.quality}/5</Tag>
              </p>
              <p>
                下次复习时间：<Tag color="green">{dayjs(reviewResult.next_review_date).format('YYYY-MM-DD HH:mm')}</Tag>
              </p>
            </Card>

            <Button type="primary" size="large" block onClick={resetReview}>
              返回复习列表
            </Button>
          </Space>
        </Card>
      </PageShell>
    )
  }

  return null
}
