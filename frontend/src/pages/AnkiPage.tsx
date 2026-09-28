import { useEffect, useState, useSyncExternalStore } from 'react'
import { Alert, Button, Card, Col, Input, InputNumber, List, Modal, Row, Segmented, Space, Tag, message } from 'antd'
import { useNavigate } from 'react-router-dom'
import {
  aiGenerateAnkiCards,
  importAnkiCardsCSV,
} from '../services/ankiApi'
import { useOfflineAnki } from '../hooks/useOfflineAnki'
import { syncEngine } from '../sync/SyncEngine'
import { getApiErrorMessage } from '../services/apiClient'
import { PageShell } from '../components/PageShell'

// 翻转状态：记录哪些卡片已翻转
type FlippedMap = Record<string, boolean>

const { TextArea } = Input

export function AnkiPage() {
  const navigate = useNavigate()
  const [scope, setScope] = useState<'due' | 'all'>('due')
  const [queueMode, setQueueMode] = useState<'review' | 'new' | 'all'>('review')
  const { cards: allCards, pendingReviews, createCard, updateCard, deleteCard, reviewCard } = useOfflineAnki()
  const sync = useSyncExternalStore(syncEngine.subscribe.bind(syncEngine), syncEngine.getSnapshot)
  const loading = sync.status === 'syncing' && allCards.length === 0
  const due = (date: string | null) => !date || Date.parse(date) <= Date.now()
  const available = allCards.filter(card => !pendingReviews.has(card._localId))
  const newQueue = available.filter(card => card.repetitions === 0 && due(card.due_at))
  const reviewQueue = available.filter(card => card.repetitions > 0 && due(card.due_at))
  const cards = (queueMode === 'new' ? newQueue : queueMode === 'review' ? reviewQueue
    : allCards.filter(card => scope === 'all' || due(card.due_at)))
    .sort((a, b) => (a.due_at || '').localeCompare(b.due_at || '') || a._localId.localeCompare(b._localId))
  const newQueueCount = newQueue.length, reviewQueueCount = reviewQueue.length
  const [editingId, setEditingId] = useState<string | null>(null)
  const [flipped, setFlipped] = useState<FlippedMap>({})

  const [manualFront, setManualFront] = useState('')
  const [manualBack, setManualBack] = useState('')
  const [manualTags, setManualTags] = useState('')
  const [csvText, setCsvText] = useState('')

  const [aiTopic, setAiTopic] = useState('')
  const [aiSourceText, setAiSourceText] = useState('')
  const [aiCount, setAiCount] = useState(5)
  const [aiTags, setAiTags] = useState('')

  const loadCards = () => syncEngine.syncAll()
  useEffect(() => { void loadCards() }, [])
  useEffect(() => { setFlipped({}) }, [scope, queueMode])

  const handleCreateManual = async () => {
    if (!manualFront.trim() || !manualBack.trim()) {
      message.warning('请填写卡片正面和背面')
      return
    }
    try {
      const data = { front: manualFront.trim(), back: manualBack.trim(), tags: manualTags.trim() }
      if (editingId) await updateCard(editingId, data)
      else await createCard(data)
      message.success('已保存到本机，联网后自动同步')
      setEditingId(null)
      setManualFront(''); setManualBack(''); setManualTags('')
    } catch (error) { message.error(getApiErrorMessage(error, '本地保存失败，请重试')) }
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

  const handleReview = async (cardId: string, quality: number) => {
    try {
      await reviewCard(cardId, quality)
      message.success('复习已保存到本机，等待云端确认')
    } catch (error) { message.error(getApiErrorMessage(error, '复习保存失败')) }
  }

  const toggleFlip = (cardId: string) => setFlipped(prev => ({ ...prev, [cardId]: !prev[cardId] }))

  const handleExportCSV = () => {
    const quote = (value: unknown) => `"${String(value ?? '').replace(/"/g, '""')}"`
    const csv = [['front', 'back', 'tags', 'note'], ...allCards.map(c => [c.front, c.back, c.tags, c.note])]
      .map(row => row.map(quote).join(',')).join('\r\n')
    const url = URL.createObjectURL(new Blob(['\ufeff', csv], { type: 'text/csv;charset=utf-8;' }))
    const a = document.createElement('a'); a.href = url; a.download = 'anki-local-cards.csv'; a.click()
    URL.revokeObjectURL(url)
    message.success(`已导出本机 ${allCards.length} 张卡片（包含待同步内容）`)
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
      {(sync.status === 'offline' || sync.lastError || pendingReviews.size > 0) && <Alert showIcon type="info"
        message={sync.lastError || (sync.status === 'offline' ? '当前离线：显示本机缓存，编辑和复习会在联网后同步' : `${pendingReviews.size} 次复习等待同步确认`)}
        action={<Button onClick={() => void syncEngine.syncAll({ retryFailed: true })}>重试同步</Button>} />}

      <Row gutter={[12, 12]}>
        <Col xs={24} lg={10}>
          <Card title={editingId ? "编辑卡片" : "手动新增卡片"} size="small" style={{ marginBottom: 12 }}>
            <Space direction="vertical" style={{ width: '100%' }}>
              <Input placeholder="正面（问题）" value={manualFront} onChange={(e) => setManualFront(e.target.value)} />
              <TextArea rows={4} placeholder="背面（答案）" value={manualBack} onChange={(e) => setManualBack(e.target.value)} />
              <Input placeholder="标签（逗号分隔，可选）" value={manualTags} onChange={(e) => setManualTags(e.target.value)} />
              <Button type="primary" onClick={handleCreateManual}>{editingId ? '保存修改' : '创建卡片'}</Button>
              {editingId && <Button onClick={() => setEditingId(null)}>取消编辑</Button>}
            </Space>
          </Card>

          <Card title="AI 注入卡片（需联网）" size="small">
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
              <Button disabled={!sync.online} onClick={handleAIGenerate}>AI 生成并注入</Button>
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
              <Button disabled={!sync.online} onClick={handleImportCSV}>导入 CSV（需联网）</Button>
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
              rowKey="_localId"
              pagination={{ pageSize: 25, showSizeChanger: true, showTotal: total => `共 ${total} 张` }}
              locale={{ emptyText: '暂无卡片' }}
              renderItem={(card) => {
                const isFlipped = !!flipped[card._localId]
                return (
                  <List.Item
                    actions={pendingReviews.has(card._localId) ? [<Tag key="pending">复习待同步</Tag>] : isFlipped ? [
                      <Button size="small" danger onClick={() => handleReview(card._localId, 2)}>忘记</Button>,
                      <Button size="small" onClick={() => handleReview(card._localId, 3)}>一般</Button>,
                      <Button size="small" type="primary" onClick={() => handleReview(card._localId, 5)}>熟练</Button>,
                    ] : [
                      <Button size="small" onClick={() => toggleFlip(card._localId)}>翻转查看答案</Button>,
                    ]}
                  >
                    <List.Item.Meta
                      title={<Space wrap><span>{card.front}</span>
                        {card._syncStatus !== 'synced' && <Tag>{card._syncStatus === 'conflicted' ? '同步冲突：请在账户菜单处理' : card._syncStatus === 'sync_failed' ? '同步失败，内容已保留' : '待同步'}</Tag>}
                        <Button size="small" disabled={pendingReviews.has(card._localId)} onClick={() => { setEditingId(card._localId); setManualFront(card.front); setManualBack(card.back); setManualTags(card.tags || '') }}>编辑</Button>
                        <Button size="small" danger disabled={pendingReviews.has(card._localId)} onClick={() => Modal.confirm({ title: '删除这张卡片？', onOk: () => deleteCard(card._localId) })}>删除</Button>
                      </Space>}
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
