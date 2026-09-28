import { useEffect, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Pin, Plus, Sparkles, Trash2 } from 'lucide-react'
import { Badge, Button, Field, IconButton, Input, Notice, Segmented, Select, Skeleton, toast } from '../../../ui'
import {
  addCustomQuote,
  deleteQuote,
  generateAIQuote,
  getMotivationSettings,
  listQuotes,
  updateMotivationSettings,
  type MotivationSettings,
} from '../../../services/motivationApi'
import { getApiErrorMessage } from '../../../services/apiClient'
import { Group, Row, Rows, settingsStyles as s } from '../SettingsDialog'

const SORTS = [
  { value: 'created_desc', label: '最新优先' },
  { value: 'created_asc', label: '最早优先' },
  { value: 'source_priority', label: '我的 → AI → 预设' },
  { value: 'author_asc', label: '按作者' },
  { value: 'content_asc', label: '按内容' },
]
const PERIODS = [
  { value: '1800', label: '30 分钟' },
  { value: '3600', label: '1 小时' },
  { value: '10800', label: '3 小时' },
  { value: '21600', label: '6 小时' },
  { value: '43200', label: '12 小时' },
  { value: '86400', label: '1 天' },
]
const SOURCE: Record<string, string> = { custom: '我的', ai: 'AI', preset: '预设' }

export function MotivationSection() {
  const qc = useQueryClient()
  const settings = useQuery({ queryKey: ['motivation', 'settings'], queryFn: getMotivationSettings })
  const quotes = useQuery({ queryKey: ['motivation', 'quotes'], queryFn: () => listQuotes() })
  const [draft, setDraft] = useState<Partial<MotivationSettings>>({})
  const [content, setContent] = useState('')
  const [author, setAuthor] = useState('')
  const [busy, setBusy] = useState<'save' | 'add' | 'ai' | null>(null)

  useEffect(() => setDraft({}), [settings.data])
  if (settings.isLoading) return <Skeleton height={260} radius={12} />
  if (!settings.data) return <Notice tone="danger">没能读取语录设置。</Notice>
  const cur = { ...settings.data, ...draft }

  const refresh = async () => {
    await qc.invalidateQueries({ queryKey: ['motivation'] })
  }
  const saveSettings = async (patch: Partial<MotivationSettings>) => {
    const next = { ...cur, ...patch }
    if (next.display_mode === 'manual' && !next.selected_quote_id) {
      toast.warning('固定展示需要先选一条语录')
      return
    }
    setBusy('save')
    try {
      await updateMotivationSettings({
        display_mode: next.display_mode,
        sort_mode: next.sort_mode,
        rotation_seconds: next.rotation_seconds,
        ...(next.selected_quote_id ? { selected_quote_id: next.selected_quote_id } : {}),
      })
      await refresh()
      toast.success('已保存')
    } catch (e) {
      toast.error(getApiErrorMessage(e, '保存失败'))
    } finally {
      setBusy(null)
    }
  }

  const add = async () => {
    if (!content.trim()) return
    setBusy('add')
    try {
      await addCustomQuote(content.trim(), author.trim() || undefined)
      setContent('')
      setAuthor('')
      await refresh()
      toast.success('已添加')
    } catch (e) {
      toast.error(getApiErrorMessage(e, '添加失败'))
    } finally {
      setBusy(null)
    }
  }

  const ai = async () => {
    setBusy('ai')
    try {
      const q = await generateAIQuote()
      await refresh()
      toast.success('生成了一条新语录', { description: q.content })
    } catch (e) {
      toast.error(getApiErrorMessage(e, '生成失败'))
    } finally {
      setBusy(null)
    }
  }

  return (
    <>
      <Group title="展示方式">
        <Rows>
          <Row label="模式" hint={cur.display_mode === 'auto' ? '按顺序定时轮换' : '一直展示你选中的那一条'}>
            <Segmented
              size="sm"
              ariaLabel="展示模式"
              value={cur.display_mode}
              onChange={v => setDraft(d => ({ ...d, display_mode: v }))}
              options={[
                { value: 'auto', label: '自动轮换' },
                { value: 'manual', label: '固定展示' },
              ]}
            />
          </Row>
          {cur.display_mode === 'auto' && (
            <>
              <Row label="轮换顺序">
                <div style={{ width: 200 }}>
                  <Select size="sm" ariaLabel="轮换顺序" value={cur.sort_mode} onValueChange={v => setDraft(d => ({ ...d, sort_mode: v }))} options={SORTS} />
                </div>
              </Row>
              <Row label="轮换周期">
                <div style={{ width: 200 }}>
                  <Select
                    size="sm"
                    ariaLabel="轮换周期"
                    value={String(cur.rotation_seconds)}
                    onValueChange={v => setDraft(d => ({ ...d, rotation_seconds: Number(v) }))}
                    options={PERIODS}
                  />
                </div>
              </Row>
            </>
          )}
        </Rows>
        <div className={s.actions} style={{ marginTop: 12 }}>
          <Button variant="primary" size="sm" loading={busy === 'save'} disabled={Object.keys(draft).length === 0} onClick={() => void saveSettings({})}>
            保存展示方式
          </Button>
        </div>
      </Group>

      <Group title="添加一条">
        <div className={s.stack}>
          <Field label="内容" htmlFor="q-content">
            <Input id="q-content" value={content} onChange={e => setContent(e.target.value)} placeholder="写给未来某个想放弃的自己" />
          </Field>
          <div className={s.actions}>
            <div style={{ flex: 1 }}>
              <Input aria-label="作者" value={author} onChange={e => setAuthor(e.target.value)} placeholder="作者（可选）" />
            </div>
            <Button icon={<Plus />} loading={busy === 'add'} disabled={!content.trim()} onClick={() => void add()}>
              添加
            </Button>
            <Button variant="ghost" icon={<Sparkles />} loading={busy === 'ai'} onClick={() => void ai()}>
              让 AI 写一条
            </Button>
          </div>
        </div>
      </Group>

      <Group title={`语录库（${quotes.data?.length ?? 0}）`}>
        <Rows>
          <ul className={s.quotes}>
            {(quotes.data ?? []).map(q => {
              const pinned = cur.display_mode === 'manual' && cur.selected_quote_id === q.id
              return (
                <li key={q.id} className={s.quoteRow} data-current={pinned || undefined}>
                  <span className={s.quoteText}>
                    {q.content}
                    <small>
                      {q.author ? `— ${q.author} · ` : ''}
                      {SOURCE[q.source_type] ?? q.source_type}
                    </small>
                  </span>
                  {pinned ? (
                    <Badge tone="evidence">正在展示</Badge>
                  ) : (
                    <IconButton label="固定展示这一条" size="sm" onClick={() => void saveSettings({ display_mode: 'manual', selected_quote_id: q.id })}>
                      <Pin />
                    </IconButton>
                  )}
                  <IconButton
                    label="删除"
                    size="sm"
                    onClick={async () => {
                      const r = await deleteQuote(q.id)
                      if (!r.ok) toast.error(r.detail || '删除失败')
                      await refresh()
                    }}
                  >
                    <Trash2 />
                  </IconButton>
                </li>
              )
            })}
          </ul>
        </Rows>
      </Group>
    </>
  )
}
