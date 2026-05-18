import { useEffect, useState } from 'react'
import { Button, Card, Col, Input, InputNumber, List, Row, Segmented, Space, Tag, message } from 'antd'
import { useNavigate } from 'react-router-dom'
import {
  aiGenerateAnkiCards,
  createAnkiCard,
  exportAnkiCardsCSV,
  getAnkiQueue,
  importAnkiCardsCSV,
  listAnkiCards,
  reviewAnkiCard,
  type AnkiCardItem,
} from '../services/ankiApi'
import { PageShell } from '../components/PageShell'

// 翻转状态：记录哪些卡片已翻转
type FlippedMap = Record<number, boolean>

const { TextArea } = Input

export function AnkiPage() {
  const navigate = useNavigate()
  const [scope, setScope] = useState<'due' | 'all'>('due')
  const [queueMode, setQueueMode] = useState<'review' | 'new' | 'all'>('review')
  const [cards, setCards] = useState<AnkiCardItem[]>([])
  const [loading, setLoading] = useState(false)
  const [newQueueCount, setNewQueueCount] = useState(0)
  const [reviewQueueCount, setReviewQueueCount] = useState(0)
  const [flipped, setFlipped] = useState<FlippedMap>({})

  const [manualFront, setManualFront] = useState('')
  const [manualBack, setManualBack] = useState('')
  const [manualTags, setManualTags] = useState('')
  const [csvText, setCsvText] = useState('')

  const [aiTopic, setAiTopic] = useState('')
  const [aiSourceText, setAiSourceText] = useState('')
  const [aiCount, setAiCount] = useState(5)
  const [aiTags, setAiTags] = useState('')

  const loadCards = async () => {
    setLoading(true)
    setFlipped({})
    if (queueMode === 'all') {
      const data = await listAnkiCards(scope, 100)
      setCards(data)
      setReviewQueueCount(data.filter((c) => c.repetitions > 0).length)
      setNewQueueCount(data.filter((c) => c.repetitions === 0).length)
      setLoading(false)
      return
    }

    const queue = await getAnkiQueue(50, 100)
    if (!queue) {
      setCards([])
      setLoading(false)
      return
    }
    setNewQueueCount(queue.new_cards.length)
    setReviewQueueCount(queue.review_cards.length)
    setCards(queueMode === 'new' ? queue.new_cards : queue.review_cards)
    setLoading(false)
  }

  useEffect(() => {
    void loadCards()
  }, [scope, queueMode])

  const handleCreateManual = async () => {
    if (!manualFront.trim() || !manualBack.trim()) {
      message.warning('请填写卡片正面和背面')
      return
    }
    const created = await createAnkiCard({
      front: manualFront.trim(),
      back: manualBack.trim(),
      tags: manualTags.trim() || undefined,
    })
    if (!created) {
      message.error('创建失败')
      return
    }
    message.success('卡片已创建')
    setManualFront('')
    setManualBack('')
    setManualTags('')
    void loadCards()
  }

  const handleAIGenerate = async () => {
    if (!aiTopic.trim()) {
      message.warning('请填写主题')
      return
    }
    const result = await aiGenerateAnkiCards({
      topic: aiTopic.trim(),
      source_text: aiSourceText.trim() || undefined,
      count: aiCount,
      tags: aiTags.trim() || undefined,
    })
    if (!result) {
      message.error('AI 生成失败，请检查 AI 配置')
      return
    }
    message.success(`AI 已生成 ${result.created} 张卡片`)
    void loadCards()
  }

  const handleReview = async (cardId: number, quality: number) => {
    const updated = await reviewAnkiCard(cardId, quality)
    if (!updated) {
      message.error('复习提交失败')
      return
    }
    message.success('已记录本次复习')
    void loadCards()
  }

  const toggleFlip = (cardId: number) => {
    setFlipped(prev => ({ ...prev, [cardId]: !prev[cardId] }))
  }

  const handleExportCSV = async () => {
    const result = await exportAnkiCardsCSV()
    if (!result) {
      message.error('导出失败')
      return
    }
    const blob = new Blob([result.csv], { type: 'text/csv;charset=utf-8;' })
    const url = window.URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = result.filename || 'anki_cards.csv'
    a.click()
    window.URL.revokeObjectURL(url)
    message.success(`已导出 ${result.count} 张卡片`)
  }

  const handleImportCSV = async () => {
    if (!csvText.trim()) {
      message.warning('请先粘贴 CSV 内容')
      return
    }
    const result = await importAnkiCardsCSV(csvText)
    if (!result) {
      message.error('导入失败，请检查 CSV 格式')
      return
    }
    message.success(`导入完成：新增 ${result.created}，跳过 ${result.skipped}`)
    setCsvText('')
    void loadCards()
  }

  return (
    <PageShell title="Anki卡片" onBack={() => navigate('/')} maxWidth={1280}>
      <Row gutter={[12, 12]}>
        <Col xs={24} lg={10}>
          <Card title="手动新增卡片" size="small" style={{ marginBottom: 12 }}>
            <Space direction="vertical" style={{ width: '100%' }}>
              <Input placeholder="正面（问题）" value={manualFront} onChange={(e) => setManualFront(e.target.value)} />
              <TextArea rows={4} placeholder="背面（答案）" value={manualBack} onChange={(e) => setManualBack(e.target.value)} />
              <Input placeholder="标签（逗号分隔，可选）" value={manualTags} onChange={(e) => setManualTags(e.target.value)} />
              <Button type="primary" onClick={handleCreateManual}>创建卡片</Button>
            </Space>
          </Card>

          <Card title="AI 注入卡片" size="small">
            <Space direction="vertical" style={{ width: '100%' }}>
              <Input placeholder="主题（例如：六级阅读长难句）" value={aiTopic} onChange={(e) => setAiTopic(e.target.value)} />
              <TextArea
                rows={6}
                placeholder="素材（可选）：粘贴文章、笔记、错题解析，AI 将据此出卡"
                value={aiSourceText}
                onChange={(e) => setAiSourceText(e.target.value)}
              />
              <InputNumber min={1} max={20} value={aiCount} onChange={(v) => setAiCount(v || 5)} style={{ width: '100%' }} />
              <Input placeholder="标签（逗号分隔，可选）" value={aiTags} onChange={(e) => setAiTags(e.target.value)} />
              <Button onClick={handleAIGenerate}>AI 生成并注入</Button>
            </Space>
          </Card>

          <Card title="CSV 导入导出" size="small" style={{ marginTop: 12 }}>
            <Space direction="vertical" style={{ width: '100%' }}>
              <Button onClick={handleExportCSV}>导出 CSV</Button>
              <TextArea
                rows={6}
                placeholder={"粘贴 CSV 内容后可直接导入\n建议表头：front,back,tags,note,source,due_at,interval_days,ease_factor,repetitions,last_quality"}
                value={csvText}
                onChange={(e) => setCsvText(e.target.value)}
              />
              <Button onClick={handleImportCSV}>导入 CSV</Button>
            </Space>
          </Card>
        </Col>

        <Col xs={24} lg={14}>
          <Card
            title="Anki 复习"
            size="small"
            extra={(
              <Segmented
                value={queueMode}
                onChange={(v) => setQueueMode(v as 'review' | 'new' | 'all')}
                options={[
                  { label: `复习队列(${reviewQueueCount})`, value: 'review' },
                  { label: `新卡队列(${newQueueCount})`, value: 'new' },
                  { label: '全部卡', value: 'all' },
                ]}
              />
            )}
          >
            {queueMode === 'all' && (
              <div style={{ marginBottom: 8 }}>
                <Segmented
                  size="small"
                  value={scope}
                  onChange={(v) => setScope(v as 'due' | 'all')}
                  options={[
                    { label: '到期', value: 'due' },
                    { label: '全部', value: 'all' },
                  ]}
                />
              </div>
            )}
            <List
              loading={loading}
              dataSource={cards}
              locale={{ emptyText: '暂无卡片' }}
              renderItem={(card) => {
                const isFlipped = !!flipped[card.id]
                return (
                  <List.Item
                    actions={isFlipped ? [
                      <Button size="small" danger onClick={() => handleReview(card.id, 2)}>忘记</Button>,
                      <Button size="small" onClick={() => handleReview(card.id, 3)}>一般</Button>,
                      <Button size="small" type="primary" onClick={() => handleReview(card.id, 5)}>熟练</Button>,
                    ] : [
                      <Button size="small" onClick={() => toggleFlip(card.id)}>翻转查看答案</Button>,
                    ]}
                  >
                    <List.Item.Meta
                      title={<span>{card.front}</span>}
                      description={isFlipped ? (
                        <Space direction="vertical" size={4}>
                          <span style={{ whiteSpace: 'pre-wrap' }}>{card.back}</span>
                          <Space wrap>
                            <Tag>{card.source}</Tag>
                            <Tag>间隔 {card.interval_days} 天</Tag>
                            <Tag>EF {(card.ease_factor / 100).toFixed(2)}</Tag>
                            {card.tags && <Tag color="purple">{card.tags}</Tag>}
                          </Space>
                        </Space>
                      ) : (
                        <span style={{ color: 'var(--text-tertiary)', fontStyle: 'italic' }}>点击翻转查看答案</span>
                      )}
                    />
                  </List.Item>
                )
              }}
            />
          </Card>
        </Col>
      </Row>
    </PageShell>
  )
}
