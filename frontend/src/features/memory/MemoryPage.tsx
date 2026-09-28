import { useMemo, useState, type CSSProperties } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowRight, Brain, CircleDot, History, Lock, LockOpen, MoreHorizontal, Pencil, RotateCcw, ScanSearch, Sparkles, Trash2, Undo2, X } from 'lucide-react'
import { Button, Confirm, Empty, IconButton, Menu, Notice, Skeleton, Tabs, toast, type MenuEntry } from '../../ui'
import {
  deleteMemory,
  listMemories,
  listMemoryConflicts,
  reviewMemoryCandidate,
  updateMemory,
  type MemoryConflict,
  type MemoryItem,
} from '../../services/memoryApi'
import { runAgentMemoryLearning } from '../../services/agentApi'
import { getApiErrorMessage } from '../../services/apiClient'
import { usePageChrome } from '../../app/shell/shellStore'
import { qk } from '../../app/queryClient'
import { shortDate } from '../../lib/dates'
import {
  STATE_META,
  confidenceLabel,
  groupMemories,
  isUserFacing,
  sourceLabel,
  stagedWithoutConflicts,
  stateOf,
  viewOf,
  type MemoryView,
} from './memoryModel'
import { EditMemoryDialog, ProvenanceDrawer } from './MemoryPanels'
import s from './memory.module.css'

export function MemoryPage() {
  const qc = useQueryClient()
  const list = useQuery({ queryKey: qk.memories, queryFn: listMemories, staleTime: 30_000 })
  const conflicts = useQuery({ queryKey: qk.memoryConflicts, queryFn: listMemoryConflicts, staleTime: 30_000 })
  const [view, setView] = useState<MemoryView>('active')
  const [busy, setBusy] = useState<Record<number, boolean>>({})
  const [provenance, setProvenance] = useState<MemoryItem | null>(null)
  const [editing, setEditing] = useState<MemoryItem | null>(null)
  const [removing, setRemoving] = useState<MemoryItem | null>(null)
  const [learning, setLearning] = useState(false)

  usePageChrome({ title: '长期记忆' })

  const items = useMemo(() => (list.data ?? []).filter(isUserFacing), [list.data])
  const conflictList = conflicts.data ?? []
  const staged = useMemo(() => stagedWithoutConflicts(items, conflictList), [items, conflictList])
  const active = useMemo(() => items.filter(m => viewOf(m) === 'active'), [items])
  const archive = useMemo(() => items.filter(m => viewOf(m) === 'archive'), [items])
  const pendingCount = staged.length + conflictList.length

  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ['memory'] })
    void qc.invalidateQueries({ queryKey: qk.memoryCandidates })
    void qc.invalidateQueries({ queryKey: qk.coreProfile })
  }
  const patch = (m: MemoryItem) => qc.setQueryData<MemoryItem[]>(qk.memories, prev => (prev ?? []).map(x => (x.id === m.id ? { ...x, ...m } : x)))
  const withBusy = async (id: number, fn: () => Promise<void>) => {
    setBusy(b => ({ ...b, [id]: true }))
    try {
      await fn()
    } finally {
      setBusy(b => ({ ...b, [id]: false }))
    }
  }

  const review = (id: number, decision: 'confirm' | 'ignore' | 'inaccurate', message: string) =>
    withBusy(id, async () => {
      const r = await reviewMemoryCandidate(id, decision, false)
      if (!r) {
        toast.error('没能处理这条记忆', { description: '它可能已经过期，或者被其他操作更新了。' })
        refresh()
        return
      }
      toast.success(message)
      refresh()
    })

  const setFlag = (m: MemoryItem, patchFields: { status?: string; is_locked?: number }, message: string) =>
    withBusy(m.id, async () => {
      const r = await updateMemory(m.id, {
        memory_value: m.memory_value,
        category: m.category,
        confidence: m.confidence,
        status: patchFields.status ?? m.status ?? 'active',
        is_locked: patchFields.is_locked ?? m.is_locked ?? 0,
      })
      if (!r) {
        toast.error('更新失败')
        return
      }
      patch(r)
      toast.success(message)
    })

  const runLearning = async () => {
    setLearning(true)
    try {
      const r = await runAgentMemoryLearning()
      if (!r) throw new Error('没能完成')
      toast.success('已重新整理长期记忆', { description: r.message || `确认 ${r.confirmed ?? 0} 条，待你确认 ${r.staged ?? 0} 条。` })
      refresh()
    } catch (error) {
      toast.error(getApiErrorMessage(error, '整理失败，请稍后重试'))
    } finally {
      setLearning(false)
    }
  }

  const loading = list.isLoading || conflicts.isLoading

  return (
    <div className={s.page}>
      <header className={s.head}>
        <div>
          <h1 className={s.title}>长期记忆</h1>
          <p className={s.lead}>
            教练回答时会参考这些关于你的事实。
            {!loading && (
              <>
                现在有 <strong>{active.length}</strong> 条生效
                {pendingCount > 0 && (
                  <>
                    ，<strong>{pendingCount}</strong> 条等你确认
                  </>
                )}
                。每一条都能查到来源，也能随时修正。
              </>
            )}
          </p>
        </div>
        <Button variant="secondary" icon={<Sparkles />} loading={learning} onClick={() => void runLearning()}>
          从最近的学习里整理
        </Button>
      </header>

      <Tabs
        className={s.tabs}
        value={view}
        onValueChange={setView}
        ariaLabel="记忆视图"
        items={[
          { value: 'active', label: '生效中', count: active.length },
          { value: 'staged', label: '待确认', count: pendingCount },
          { value: 'archive', label: '已归档', count: archive.length },
        ]}
      />

      {loading ? (
        <div className={s.skel} aria-busy="true" aria-label="正在加载记忆">
          {[0, 1, 2, 3].map(i => (
            <Skeleton key={i} height={52} radius={10} />
          ))}
        </div>
      ) : list.isError ? (
        <Notice tone="danger" title="记忆没能加载" actions={<Button size="sm" onClick={() => void list.refetch()}>重试</Button>}>
          确认本地学习服务已经启动。
        </Notice>
      ) : view === 'staged' ? (
        pendingCount === 0 ? (
          <Empty icon={<Brain />} title="没有等你确认的记忆" body="低风险的聚合结论会自动生效；敏感或主观的推断会先放到这里等你点头。" />
        ) : (
          <>
            {conflictList.length > 0 && (
              <section className={s.section} aria-labelledby="conflicts-title">
                <div className={s.sectionHead}>
                  <h2 id="conflicts-title" className={s.sectionTitle}>
                    说法变了
                  </h2>
                  <span className={s.sectionMeta}>同一件事出现了新旧两种说法，选一个作数</span>
                </div>
                {conflictList.map((c, i) => (
                  <ConflictCard
                    key={c.candidate_memory_id}
                    conflict={c}
                    index={i}
                    busy={Boolean(busy[c.candidate_memory_id])}
                    onAccept={() => void review(c.candidate_memory_id, 'confirm', '已采用新说法，旧的保留在历史里')}
                    onKeep={() => void review(c.candidate_memory_id, 'inaccurate', '已保留原来的说法')}
                  />
                ))}
              </section>
            )}
            {staged.length > 0 && (
              <section className={s.section} aria-labelledby="staged-title">
                <div className={s.sectionHead}>
                  <h2 id="staged-title" className={s.sectionTitle}>
                    新发现
                  </h2>
                  <span className={s.sectionMeta}>确认后教练才会用它</span>
                </div>
                <Ledger
                  items={staged}
                  busy={busy}
                  onProvenance={setProvenance}
                  renderActions={m => (
                    <>
                      <Button size="sm" variant="primary" loading={busy[m.id]} onClick={() => void review(m.id, 'confirm', '已确认')}>
                        确认
                      </Button>
                      <Button size="sm" variant="ghost" disabled={busy[m.id]} onClick={() => void review(m.id, 'inaccurate', '已标记为不准确')}>
                        不准确
                      </Button>
                      <IconButton label="查看来源" size="sm" onClick={() => setProvenance(m)}>
                        <ScanSearch />
                      </IconButton>
                    </>
                  )}
                />
              </section>
            )}
          </>
        )
      ) : view === 'active' ? (
        active.length === 0 ? (
          <Empty
            icon={<Brain />}
            title="还没有生效的记忆"
            body="和教练多聊几次、完成几轮复习后，它会从中总结出你的目标、偏好和薄弱点，确认后记在这里。"
            actions={
              <Button variant="secondary" icon={<Sparkles />} loading={learning} onClick={() => void runLearning()}>
                现在整理一次
              </Button>
            }
          />
        ) : (
          <GroupedLedger
            items={active}
            busy={busy}
            onProvenance={setProvenance}
            menuFor={m => [
              { key: 'edit', label: '修正', icon: <Pencil />, onSelect: () => setEditing(m) },
              m.is_locked
                ? { key: 'unlock', label: '解除锁定', icon: <LockOpen />, onSelect: () => void setFlag(m, { is_locked: 0 }, '已解除锁定') }
                : { key: 'lock', label: '锁定，不许自动改写', icon: <Lock />, onSelect: () => void setFlag(m, { is_locked: 1 }, '已锁定') },
              { key: 'source', label: '查看来源', icon: <History />, onSelect: () => setProvenance(m) },
              { key: 'sep', type: 'separator' },
              { key: 'ignore', label: '先不用这条', icon: <X />, onSelect: () => void setFlag(m, { status: 'ignored' }, '教练不会再参考这条') },
              { key: 'delete', label: '删除', icon: <Trash2 />, tone: 'danger', onSelect: () => setRemoving(m) },
            ]}
          />
        )
      ) : archive.length === 0 ? (
        <Empty icon={<History />} title="没有归档的记忆" body="被忽略、过期或被新说法取代的记忆会留在这里，随时可以恢复。" />
      ) : (
        <GroupedLedger
          items={archive}
          busy={busy}
          onProvenance={setProvenance}
          menuFor={m => [
            ...(stateOf(m) === 'ignored'
              ? [{ key: 'restore', label: '恢复使用', icon: <Undo2 />, onSelect: () => void setFlag(m, { status: 'active' }, '已恢复') } as MenuEntry]
              : []),
            { key: 'source', label: '查看来源', icon: <History />, onSelect: () => setProvenance(m) },
            { key: 'sep', type: 'separator' },
            { key: 'delete', label: '删除', icon: <Trash2 />, tone: 'danger', onSelect: () => setRemoving(m) },
          ]}
        />
      )}

      <ProvenanceDrawer memory={provenance} onOpenChange={v => !v && setProvenance(null)} />
      <EditMemoryDialog memory={editing} onOpenChange={v => !v && setEditing(null)} onSaved={m => { patch(m); refresh() }} />
      <Confirm
        open={Boolean(removing)}
        onOpenChange={v => !v && setRemoving(null)}
        tone="danger"
        title="删除这条记忆？"
        description="删除后教练不再知道这件事，它的变化记录也会一起删除。只是暂时不想用的话，可以选择“先不用这条”。"
        confirmLabel="删除"
        onConfirm={async () => {
          if (!removing) return
          const ok = await deleteMemory(removing.id)
          if (!ok) {
            toast.error('删除失败')
            throw new Error('delete failed')
          }
          qc.setQueryData<MemoryItem[]>(qk.memories, prev => (prev ?? []).filter(x => x.id !== removing.id))
          toast.success('已删除')
          refresh()
        }}
      />
    </div>
  )
}

/* ============================================================================
   Conflict: then vs. now, side by side
   ========================================================================== */
function ConflictCard({
  conflict,
  index,
  busy,
  onAccept,
  onKeep,
}: {
  conflict: MemoryConflict
  index: number
  busy: boolean
  onAccept: () => void
  onKeep: () => void
}) {
  return (
    <article className={s.conflict} style={{ '--i': index } as CSSProperties} aria-label="说法冲突">
      <div className={s.conflictHead}>
        <RotateCcw aria-hidden />
        {sourceLabel(conflict.candidate.source_type)} · {conflict.candidate.observed_at ? shortDate(conflict.candidate.observed_at) : ''}
      </div>
      <div className={s.versus}>
        <div className={s.side} data-side="old">
          <span className={s.sideLabel}>现在教练相信</span>
          <p className={s.sideValue}>{conflict.current.value}</p>
          <span className={s.sideMeta}>{conflict.current.observed_at ? `${shortDate(conflict.current.observed_at)} 记下` : ''}</span>
        </div>
        <span className={s.arrow} aria-hidden>
          <ArrowRight />
        </span>
        <div className={s.side} data-side="new">
          <span className={s.sideLabel}>最近观察到</span>
          <p className={s.sideValue}>{conflict.candidate.value}</p>
          <span className={s.sideMeta}>{confidenceLabel(conflict.candidate.confidence)}</span>
        </div>
      </div>
      <div className={s.conflictActions}>
        <Button size="sm" variant="ghost" disabled={busy} onClick={onKeep}>
          保留原来的
        </Button>
        <Button size="sm" variant="primary" loading={busy} onClick={onAccept}>
          采用新说法
        </Button>
      </div>
    </article>
  )
}

/* ============================================================================
   Ledger
   ========================================================================== */
function GroupedLedger({
  items,
  busy,
  onProvenance,
  menuFor,
}: {
  items: MemoryItem[]
  busy: Record<number, boolean>
  onProvenance: (m: MemoryItem) => void
  menuFor: (m: MemoryItem) => MenuEntry[]
}) {
  const groups = groupMemories(items)
  return (
    <>
      {groups.map(g => (
        <section key={g.label} className={s.group} aria-label={g.label}>
          <h2 className={s.groupTitle}>
            {g.label}
            <span>{g.items.length}</span>
          </h2>
          <Ledger
            items={g.items}
            busy={busy}
            onProvenance={onProvenance}
            renderActions={m => (
              <Menu
                items={menuFor(m)}
                trigger={
                  <IconButton label="操作" size="sm" disabled={busy[m.id]}>
                    <MoreHorizontal />
                  </IconButton>
                }
              />
            )}
          />
        </section>
      ))}
    </>
  )
}

function Ledger({
  items,
  busy,
  onProvenance,
  renderActions,
}: {
  items: MemoryItem[]
  busy: Record<number, boolean>
  onProvenance: (m: MemoryItem) => void
  renderActions: (m: MemoryItem) => React.ReactNode
}) {
  return (
    <ul className={s.list}>
      {items.map(m => {
        const st = stateOf(m)
        return (
          <li key={m.id} className={s.entry} data-state={st} data-locked={m.is_locked ? true : undefined} aria-busy={busy[m.id] || undefined}>
            <span className={s.bullet} aria-hidden>
              {m.is_locked ? <Lock /> : <CircleDot />}
            </span>
            <div>
              <p className={s.value}>{m.memory_value}</p>
              <div className={s.meta}>
                {st !== 'active' && <span style={{ fontWeight: 560 }}>{STATE_META[st].label}</span>}
                <span>{confidenceLabel(m.confidence)}</span>
                <span>{sourceLabel(m.source_type)}</span>
                {m.last_seen_at && <span>{shortDate(m.last_seen_at)}</span>}
                {m.expires_at && <span>到 {shortDate(m.expires_at)} 失效</span>}
                <button
                  type="button"
                  onClick={() => onProvenance(m)}
                  style={{ padding: 0, border: 0, background: 'none', color: 'var(--mx-ink-text)', font: 'inherit', cursor: 'pointer' }}
                >
                  来源
                </button>
              </div>
            </div>
            <span className={s.actions}>{renderActions(m)}</span>
          </li>
        )
      })}
    </ul>
  )
}
