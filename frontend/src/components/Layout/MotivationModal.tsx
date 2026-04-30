import { Modal, Card, Segmented, Select, Button, Input, List, Tag } from 'antd'
import type { MotivationQuote, MotivationSettings } from '../../services/motivationApi'

const QUOTE_SORT_OPTIONS = [
  { label: '最新优先', value: 'created_desc' },
  { label: '最早优先', value: 'created_asc' },
  { label: '来源优先（自定义→AI→预设）', value: 'source_priority' },
  { label: '作者 A→Z', value: 'author_asc' },
  { label: '内容 A→Z', value: 'content_asc' },
]

const QUOTE_ROTATION_OPTIONS = [
  { label: '30分钟', value: 30 * 60 },
  { label: '1小时', value: 60 * 60 },
  { label: '3小时', value: 3 * 60 * 60 },
  { label: '6小时', value: 6 * 60 * 60 },
  { label: '12小时', value: 12 * 60 * 60 },
  { label: '1天', value: 24 * 60 * 60 },
]

const { TextArea } = Input

interface MotivationModalProps {
  open: boolean
  onClose: () => void
  allQuotes: MotivationQuote[]
  motivationSettings: MotivationSettings
  setMotivationSettings: React.Dispatch<React.SetStateAction<MotivationSettings>>
  savingMotivationSettings: boolean
  newQuoteContent: string
  setNewQuoteContent: (v: string) => void
  newQuoteAuthor: string
  setNewQuoteAuthor: (v: string) => void
  onSaveSettings: () => void
  onAddQuote: () => void
  onDeleteQuote: (id: number) => void
  onPinQuote: (id: number) => void
}

export function MotivationModal({
  open, onClose, allQuotes, motivationSettings, setMotivationSettings,
  savingMotivationSettings, newQuoteContent, setNewQuoteContent,
  newQuoteAuthor, setNewQuoteAuthor, onSaveSettings, onAddQuote, onDeleteQuote, onPinQuote,
}: MotivationModalProps) {
  return (
    <Modal title="管理激励语录" open={open} onCancel={onClose} footer={null} width={520}>
      <Card size="small" style={{ marginBottom: 12, background: 'rgba(251, 191, 36, 0.05)', borderColor: 'rgba(251, 191, 36, 0.2)' }}>
        <div style={{ display: 'grid', gap: 8 }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
            <span style={{ fontSize: 12, color: 'var(--text-secondary)' }}>展示模式</span>
            <Segmented
              size="small"
              value={motivationSettings.display_mode}
              options={[{ label: '自动轮换', value: 'auto' }, { label: '固定展示', value: 'manual' }]}
              onChange={(v) => setMotivationSettings((prev) => ({ ...prev, display_mode: v as 'auto' | 'manual' }))}
            />
          </div>

          {motivationSettings.display_mode === 'manual' && (
            <div style={{ display: 'grid', gap: 4 }}>
              <span style={{ fontSize: 12, color: 'var(--text-secondary)' }}>固定语录</span>
              <Select
                size="small"
                placeholder="选择一条语录作为固定展示"
                value={motivationSettings.selected_quote_id ?? undefined}
                onChange={(v) => setMotivationSettings((prev) => ({ ...prev, selected_quote_id: Number(v) }))}
                options={allQuotes.map((q) => ({ value: q.id, label: `${q.content.slice(0, 36)}${q.content.length > 36 ? '…' : ''}` }))}
              />
            </div>
          )}

          <div style={{ display: 'grid', gap: 4 }}>
            <span style={{ fontSize: 12, color: 'var(--text-secondary)' }}>轮换顺序</span>
            <Select size="small" value={motivationSettings.sort_mode} onChange={(v) => setMotivationSettings((prev) => ({ ...prev, sort_mode: String(v) }))} options={QUOTE_SORT_OPTIONS} />
          </div>

          <div style={{ display: 'grid', gap: 4 }}>
            <span style={{ fontSize: 12, color: 'var(--text-secondary)' }}>轮换周期</span>
            <Select size="small" value={motivationSettings.rotation_seconds} onChange={(v) => setMotivationSettings((prev) => ({ ...prev, rotation_seconds: Number(v) }))} options={QUOTE_ROTATION_OPTIONS} />
          </div>

          <Button type="primary" loading={savingMotivationSettings} onClick={onSaveSettings}>保存展示设置</Button>
        </div>
      </Card>

      <div style={{ marginBottom: 12 }}>
        <TextArea placeholder="写一句你喜欢的激励语录..." value={newQuoteContent} onChange={(e) => setNewQuoteContent(e.target.value)} autoSize={{ minRows: 2, maxRows: 4 }} />
        <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
          <Input placeholder="作者/来源（可选）" value={newQuoteAuthor} onChange={(e) => setNewQuoteAuthor(e.target.value)} />
          <Button type="primary" onClick={onAddQuote}>添加</Button>
        </div>
      </div>

      <List
        size="small"
        dataSource={allQuotes}
        locale={{ emptyText: '暂无语录' }}
        renderItem={(item) => (
          <List.Item
            actions={[
              <Button key="pin" type="text" size="small" disabled={savingMotivationSettings} onClick={() => onPinQuote(item.id)}>设为当前</Button>,
              <Button key="del" type="text" danger size="small" onClick={() => onDeleteQuote(item.id)}>删除</Button>,
            ]}
          >
            <List.Item.Meta
              title={
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <span style={{ fontSize: 13, fontWeight: 500 }}>{item.content}</span>
                  {motivationSettings.selected_quote_id === item.id && <Tag color="gold" style={{ fontSize: 10, lineHeight: '16px' }}>当前固定</Tag>}
                  <Tag color={item.source_type === 'preset' ? 'default' : item.source_type === 'ai' ? 'purple' : 'blue'} style={{ fontSize: 10, lineHeight: '16px' }}>
                    {item.source_type === 'preset' ? '预设' : item.source_type === 'ai' ? 'AI' : '自定义'}
                  </Tag>
                </div>
              }
              description={item.author ? `—— ${item.author}` : undefined}
            />
          </List.Item>
        )}
      />
    </Modal>
  )
}
