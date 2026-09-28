import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Ellipsis, MessageSquarePlus, Pencil, Pin, PinOff, Search, Trash2 } from 'lucide-react'
import { Button, Chip, Confirm, IconButton, Input, Menu, Skeleton, toast } from '../../ui'
import {
  deleteConversation,
  listConversations,
  listProjects,
  updateConversation,
  type Conversation,
} from '../../services/conversationApi'
import { getConversationPath } from '../../services/conversationRoute'
import { qk } from '../../app/queryClient'
import s from './coach.module.css'

function bucket(iso: string): string {
  const d = new Date(iso.includes('T') || iso.endsWith('Z') ? iso : `${iso.replace(' ', 'T')}Z`)
  if (Number.isNaN(d.getTime())) return '更早'
  const start = new Date()
  start.setHours(0, 0, 0, 0)
  const diff = (start.getTime() - d.getTime()) / 86_400_000
  if (d.getTime() >= start.getTime()) return '今天'
  if (diff <= 1) return '昨天'
  if (diff <= 7) return '过去 7 天'
  if (diff <= 30) return '过去 30 天'
  return '更早'
}

const ORDER = ['置顶', '今天', '昨天', '过去 7 天', '过去 30 天', '更早']

export function ConversationList({
  activeId,
  projectId,
  onProjectChange,
  onNew,
}: {
  activeId: number | null
  projectId: number | null
  onProjectChange: (id: number | null) => void
  onNew: () => void
}) {
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [search, setSearch] = useState('')
  const [renaming, setRenaming] = useState<{ id: number; title: string } | null>(null)
  const [deleting, setDeleting] = useState<Conversation | null>(null)
  const convs = useQuery({
    queryKey: qk.conversations(search.trim(), projectId ?? undefined),
    queryFn: () => listConversations({ search: search.trim() || undefined, project_id: projectId ?? undefined }),
    placeholderData: prev => prev,
  })
  const projects = useQuery({ queryKey: qk.projects, queryFn: listProjects, staleTime: 60_000 })

  const groups = useMemo(() => {
    const map = new Map<string, Conversation[]>()
    for (const c of convs.data ?? []) {
      const key = c.is_pinned ? '置顶' : bucket(c.updated_at)
      map.set(key, [...(map.get(key) ?? []), c])
    }
    return ORDER.filter(k => map.has(k)).map(k => ({ key: k, items: map.get(k)! }))
  }, [convs.data])

  const invalidate = () => qc.invalidateQueries({ queryKey: ['conversations'] })

  const rename = async () => {
    if (!renaming) return
    const title = renaming.title.trim()
    if (!title) {
      setRenaming(null)
      return
    }
    try {
      await updateConversation(renaming.id, { title })
      await invalidate()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : '重命名失败')
    }
    setRenaming(null)
  }

  const togglePin = async (c: Conversation) => {
    try {
      await updateConversation(c.id, { is_pinned: !c.is_pinned })
      await invalidate()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : '操作失败')
    }
  }

  return (
    <nav className={s.list} aria-label="对话列表">
      <div className={s.listHead}>
        <Button variant="secondary" icon={<MessageSquarePlus />} className={s.newChat} onClick={onNew}>
          新对话
        </Button>
        <Input
          size="sm"
          prefix={<Search />}
          placeholder="搜索对话…"
          value={search}
          onChange={e => setSearch(e.target.value)}
          aria-label="搜索对话"
        />
        {(projects.data ?? []).length > 0 && (
          <div className={s.projects}>
            <Chip selected={projectId === null} onClick={() => onProjectChange(null)}>
              全部
            </Chip>
            {(projects.data ?? [])
              .filter(p => !p.is_archived)
              .map(p => (
                <Chip key={p.id} selected={projectId === p.id} onClick={() => onProjectChange(p.id)}>
                  {p.name}
                </Chip>
              ))}
          </div>
        )}
      </div>
      <div className={s.listScroll}>
        {convs.isLoading ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6, padding: '8px 6px' }}>
            {[0, 1, 2, 3].map(i => (
              <Skeleton key={i} height={34} radius={7} />
            ))}
          </div>
        ) : groups.length === 0 ? (
          <p className={s.listGroup} style={{ lineHeight: 1.6 }}>
            {search ? '没有找到匹配的对话。' : '还没有对话。问教练第一个问题吧。'}
          </p>
        ) : (
          groups.map(g => (
            <div key={g.key}>
              <div className={s.listGroup}>{g.key}</div>
              {g.items.map(c =>
                renaming?.id === c.id ? (
                  <div key={c.id} className={s.conv}>
                    <Input
                      size="sm"
                      autoFocus
                      wrapperClassName={s.renameInput}
                      value={renaming.title}
                      onChange={e => setRenaming({ id: c.id, title: e.target.value })}
                      onBlur={() => void rename()}
                      onKeyDown={e => {
                        if (e.key === 'Enter') void rename()
                        if (e.key === 'Escape') {
                          e.preventDefault()
                          setRenaming(null)
                        }
                      }}
                      aria-label="对话标题"
                    />
                  </div>
                ) : (
                  <div key={c.id} className={s.conv} aria-current={c.id === activeId ? 'page' : undefined}>
                    <button type="button" className={s.convBtn} onClick={() => navigate(getConversationPath(c.id))}>
                      <span className={s.convTitle}>
                        {c.is_pinned && <Pin aria-label="已置顶" />}
                        {c.title || '未命名对话'}
                      </span>
                      {c.matched_preview && <span className={s.convMeta}>{c.matched_preview}</span>}
                    </button>
                    <span className={s.convMore}>
                      <Menu
                        align="end"
                        trigger={
                          <IconButton label="更多操作" size="sm" noTooltip>
                            <Ellipsis />
                          </IconButton>
                        }
                        items={[
                          { key: 'rename', label: '重命名', icon: <Pencil />, onSelect: () => setRenaming({ id: c.id, title: c.title }) },
                          { key: 'pin', label: c.is_pinned ? '取消置顶' : '置顶', icon: c.is_pinned ? <PinOff /> : <Pin />, onSelect: () => void togglePin(c) },
                          { key: 'sep', type: 'separator' },
                          { key: 'del', label: '删除', icon: <Trash2 />, tone: 'danger', onSelect: () => setDeleting(c) },
                        ]}
                      />
                    </span>
                  </div>
                ),
              )}
            </div>
          ))
        )}
      </div>
      <Confirm
        open={!!deleting}
        onOpenChange={v => !v && setDeleting(null)}
        tone="danger"
        title="删除这段对话？"
        description={`「${deleting?.title ?? ''}」及其消息会被永久删除，已经写入的笔记和任务不受影响。`}
        confirmLabel="删除"
        onConfirm={async () => {
          if (!deleting) return
          try {
            await deleteConversation(deleting.id)
            await invalidate()
            if (deleting.id === activeId) navigate('/', { replace: true })
            toast.success('对话已删除')
          } catch (e) {
            toast.error(e instanceof Error ? e.message : '删除失败')
            throw e
          }
        }}
      />
    </nav>
  )
}
