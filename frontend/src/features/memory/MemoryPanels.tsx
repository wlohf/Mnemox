import { useEffect, useState, type CSSProperties } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Button, Dialog, Drawer, Field, Input, KeyValue, Skeleton, Slider, Textarea, Badge, toast } from '../../ui'
import { correctMemory, listMemoryDeclarations, updateMemory, type MemoryItem } from '../../services/memoryApi'
import { getApiErrorMessage } from '../../services/apiClient'
import { shortDate } from '../../lib/dates'
import { categoryLabel, confidenceLabel, creatorLabel, evidenceLines, sourceLabel, STATE_META, stateOf, timeline } from './memoryModel'
import s from './memory.module.css'

const DECL_TONE: Record<string, string> = {
  confirmed: 'var(--mx-success)',
  staged: 'var(--mx-evidence)',
  inaccurate: 'var(--mx-danger)',
  expired: 'var(--mx-warning)',
}

const DECL_LABEL: Record<string, string> = {
  confirmed: '已确认',
  staged: '待确认',
  ignored: '已忽略',
  inaccurate: '标记为不准确',
  expired: '已失效',
  superseded: '被新事实取代',
}

/* ============================================================================
   Provenance — where a memory came from and how it changed
   ========================================================================== */
export function ProvenanceDrawer({ memory, onOpenChange }: { memory: MemoryItem | null; onOpenChange: (v: boolean) => void }) {
  const history = useQuery({
    queryKey: ['memory', 'declarations', memory?.id ?? 0],
    queryFn: () => listMemoryDeclarations(memory!.id),
    enabled: memory != null,
  })
  const st = memory ? stateOf(memory) : 'active'
  return (
    <Drawer open={memory != null} onOpenChange={onOpenChange} title="这条记忆从哪来" description="教练只会引用生效中的记忆。每一次提炼、确认和修正都记录在下面。" width={30}>
      {memory && (
        <>
          <p className={s.fact}>{memory.memory_value}</p>
          <KeyValue
            className={s.kv}
            items={[
              ['状态', <Badge key="st" tone={STATE_META[st].tone}>{STATE_META[st].label}</Badge>],
              ['类别', categoryLabel(memory.category)],
              ['把握程度', `${confidenceLabel(memory.confidence)}（${Math.round((memory.confidence ?? 0) * 100)}%）`],
              ['来源', sourceLabel(memory.source_type)],
              ['最近一次出现', memory.last_seen_at ? shortDate(memory.last_seen_at) : '—'],
              ['有效期', memory.expires_at ? `到 ${shortDate(memory.expires_at)}` : '长期'],
              ['锁定', memory.is_locked ? '已锁定，不会被自动改写' : '否'],
            ]}
          />
          <h3 className={s.historyTitle}>变化记录</h3>
          {history.isLoading ? (
            <div className={s.skel}>
              <Skeleton height={48} />
              <Skeleton height={48} />
            </div>
          ) : (history.data ?? []).length === 0 ? (
            <p className={s.reason}>这是较早的记忆，当时还没有逐条记录来源。之后的确认和修正会出现在这里。</p>
          ) : (
            <ol className={s.history}>
              {timeline(history.data ?? []).map(d => {
                const lines = evidenceLines(d.evidence)
                return (
                  <li key={d.id} className={s.event} style={{ '--dot': DECL_TONE[d.review_status] } as CSSProperties}>
                    <div className={s.eventHead}>
                      <strong style={{ color: 'var(--mx-text)' }}>{DECL_LABEL[d.review_status] ?? d.review_status}</strong>
                      <span>由{creatorLabel(d.created_by)}记录</span>
                      <span>{d.observed_at ? shortDate(d.observed_at) : ''}</span>
                      <span>{sourceLabel(d.source_type)}</span>
                    </div>
                    <p className={s.eventValue}>{d.value}</p>
                    {lines.length > 0 && (
                      <ul className={s.evidence}>
                        {lines.map((l, i) => (
                          <li key={i}>{l}</li>
                        ))}
                      </ul>
                    )}
                    {d.resolution_reason && <p className={s.reason}>处理说明：{d.resolution_reason}</p>}
                  </li>
                )
              })}
            </ol>
          )}
        </>
      )}
    </Drawer>
  )
}

/* ============================================================================
   Edit — a correction is recorded as a new declaration, not an overwrite
   ========================================================================== */
export function EditMemoryDialog({
  memory,
  onOpenChange,
  onSaved,
}: {
  memory: MemoryItem | null
  onOpenChange: (v: boolean) => void
  onSaved: (m: MemoryItem) => void
}) {
  const [value, setValue] = useState('')
  const [confidence, setConfidence] = useState(0.7)
  const [expiry, setExpiry] = useState('')
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (!memory) return
    setValue(memory.memory_value)
    setConfidence(Number(memory.confidence ?? 0.7))
    setExpiry(memory.expires_at ? memory.expires_at.slice(0, 10) : '')
    setReason('')
  }, [memory])

  const save = async () => {
    if (!memory) return
    if (!value.trim()) {
      toast.warning('内容不能为空')
      return
    }
    setBusy(true)
    try {
      const nextExpiry = expiry ? `${expiry}T23:59:59` : null
      const prevExpiry = memory.expires_at ? `${memory.expires_at.slice(0, 10)}T23:59:59` : null
      const semantic = value.trim() !== memory.memory_value || Math.abs(confidence - Number(memory.confidence ?? 0.7)) > 0.001 || nextExpiry !== prevExpiry
      const saved = semantic
        ? await correctMemory(memory.id, {
            memory_value: value.trim(),
            category: memory.category,
            confidence,
            expires_at: nextExpiry,
            reason: reason.trim() || '在长期记忆页手动修正',
          })
        : await updateMemory(memory.id, {
            memory_value: memory.memory_value,
            category: memory.category,
            confidence: memory.confidence,
            status: memory.status,
            is_locked: memory.is_locked,
          })
      if (!saved) throw new Error('保存失败')
      onSaved(saved)
      toast.success(semantic ? '已修正，并记录在变化记录里' : '已保存', { description: semantic ? '修正后的内容不会再被自动覆盖。' : undefined })
      onOpenChange(false)
    } catch (error) {
      toast.error(getApiErrorMessage(error, '保存失败'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Dialog
      open={memory != null}
      onOpenChange={onOpenChange}
      title="修正这条记忆"
      description="改动会作为一次修正记录下来，原来的说法保留在历史里。"
      width={34}
      footer={
        <>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            取消
          </Button>
          <Button variant="primary" loading={busy} onClick={() => void save()}>
            保存修正
          </Button>
        </>
      }
    >
      <div className={s.form}>
        <Field label="教练记住的内容" htmlFor="mem-value">
          <Textarea id="mem-value" autoFocus reading autoGrow rows={2} maxHeight={200} value={value} onChange={e => setValue(e.target.value)} />
        </Field>
        <div className={s.formRow}>
          <Field label="把握程度">
            <div className={s.confRow}>
              <Slider ariaLabel="把握程度" min={0} max={1} step={0.05} value={confidence} onValueChange={setConfidence} />
              <span className={s.confValue}>{confidenceLabel(confidence)}</span>
            </div>
          </Field>
          <Field label="有效到" htmlFor="mem-expiry" optional hint="留空表示长期有效">
            <Input id="mem-expiry" type="date" value={expiry} onChange={e => setExpiry(e.target.value)} />
          </Field>
        </div>
        <Field label="为什么修正" htmlFor="mem-reason" optional>
          <Input id="mem-reason" maxLength={255} value={reason} placeholder="例如：最近改成早上学习了" onChange={e => setReason(e.target.value)} />
        </Field>
      </div>
    </Dialog>
  )
}
