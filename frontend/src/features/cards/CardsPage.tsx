import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowUpDown, Check, Layers, MessageSquareText, MoreHorizontal, Pencil, Play, Plus, Search, Sparkles, Trash2, X } from 'lucide-react'
import { Badge, Button, Chip, Confirm, Empty, IconButton, Input, Menu, Notice, Segmented, Skeleton, toast } from '../../ui'
import { deleteAnkiCard, getAnkiQueue, listAnkiCards, type AnkiCardItem } from '../../services/ankiApi'
import { getApiErrorMessage } from '../../services/apiClient'
import { usePageChrome } from '../../app/shell/shellStore'
import { qk } from '../../app/queryClient'
import {
  STATE_META,
  countDeck,
  filterDeck,
  scheduleLabel,
  sessionQueue,
  stateOf,
  tagCounts,
  type DeckFilter,
} from './cardModel'
import { StudySession } from './StudySession'
import { CardDialog, CsvDialog, GenerateDialog } from './CardDialogs'
import s from './cards.module.css'

const DECK_KEY = ['anki', 'deck'] as const
const QUEUE_KEY = ['anki', 'queue'] as const
const DECK_LIMIT = 200
const NEW_PER_DAY = 20
const PAGE = 40

export function CardsPage() {
  const navigate = useNavigate()
  const qc = useQueryClient()
  const deck = useQuery({ queryKey: DECK_KEY, queryFn: () => listAnkiCards('all', DECK_LIMIT), staleTime: 30_000 })
  const queue = useQuery({ queryKey: QUEUE_KEY, queryFn: () => getAnkiQueue(NEW_PER_DAY, 200), staleTime: 30_000 })
  const [session, setSession] = useState<AnkiCardItem[] | null>(null)
  const [filter, setFilter] = useState<DeckFilter>('all')
  const [tag, setTag] = useState<string | null>(null)
  const [query, setQuery] = useState('')
  const [shown, setShown] = useState(PAGE)
  const [editing, setEditing] = useState<{ card: AnkiCardItem | null } | null>(null)
  const [generating, setGenerating] = useState(false)
  const [csvOpen, setCsvOpen] = useState(false)
  const [removing, setRemoving] = useState<AnkiCardItem | null>(null)

  const cards = deck.data ?? []
  const counts = useMemo(() => countDeck(cards), [cards])
  const tags = useMemo(() => tagCounts(cards).slice(0, 16), [cards])
  const filtered = useMemo(() => filterDeck(cards, filter, tag, query), [cards, filter, tag, query])
  const today = useMemo(() => sessionQueue(queue.data?.review_cards ?? [], queue.data?.new_cards ?? [], NEW_PER_DAY), [queue.data])
  const dueCount = queue.data?.review_cards.length ?? 0
  const newCount = Math.min(NEW_PER_DAY, queue.data?.new_cards.length ?? 0)

  usePageChrome({ title: '记忆卡' })

  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ['anki'] })
    void qc.invalidateQueries({ queryKey: qk.dashboard })
  }

  const upsertLocal = (card: AnkiCardItem, created: boolean) => {
    qc.setQueryData<AnkiCardItem[]>(DECK_KEY, prev => (created ? [card, ...(prev ?? [])] : (prev ?? []).map(c => (c.id === card.id ? card : c))))
    void qc.invalidateQueries({ queryKey: QUEUE_KEY })
  }

  if (session) {
    return (
      <div className={s.page}>
        <StudySession
          queue={session}
          onExit={reviewed => {
            setSession(null)
            refresh()
            if (reviewed > 0) void qc.invalidateQueries({ queryKey: ['review'] })
          }}
        />
      </div>
    )
  }

  const loading = deck.isLoading || queue.isLoading
  return (
    <div className={s.page}>
      <header className={s.head}>
        <div>
          <h1 className={s.title}>记忆卡</h1>
          <p className={s.lead}>
            {cards.length === 0 ? (
              '把值得记住的东西写成一问一答，按间隔复习。'
            ) : (
              <>
                共 <strong>{counts.total}</strong> 张，<strong>{counts.mature}</strong> 张已熟练
                {counts.learning > 0 && (
                  <>
                    ，<strong>{counts.learning}</strong> 张在学习中
                  </>
                )}
                。
              </>
            )}
          </p>
        </div>
        <div className={s.headActions}>
          <Button variant="ghost" icon={<Sparkles />} onClick={() => setGenerating(true)}>
            AI 出卡
          </Button>
          <Button variant="secondary" icon={<Plus />} onClick={() => setEditing({ card: null })}>
            写一张卡
          </Button>
          <Menu
            items={[{ key: 'csv', label: '导入 / 导出 CSV', icon: <ArrowUpDown />, onSelect: () => setCsvOpen(true) }]}
            trigger={
              <IconButton label="更多">
                <MoreHorizontal />
              </IconButton>
            }
          />
        </div>
      </header>

      {loading ? (
        <Skeleton height={96} radius={14} style={{ marginBottom: 32 }} />
      ) : queue.isError ? (
        <Notice tone="danger" title="今天的复习没能加载" actions={<Button size="sm" onClick={() => void queue.refetch()}>重试</Button>} className={s.today}>
          确认本地学习服务已经启动。
        </Notice>
      ) : cards.length > 0 ? (
        <section className={s.today} data-empty={today.length === 0 || undefined} aria-label="今天的复习">
          <span className={s.stack} aria-hidden>
            <span />
            <span />
            <span>{today.length || <Check aria-label="已完成" />}</span>
          </span>
          <div className={s.todayText}>
            <h2 className={s.todayTitle}>{today.length > 0 ? `今天有 ${today.length} 张卡等你` : '今天的卡都复习完了'}</h2>
            <p className={s.todayMeta}>
              {today.length > 0
                ? [dueCount > 0 && `${dueCount} 张到期复习`, newCount > 0 && `${newCount} 张新卡`].filter(Boolean).join(' · ') + ' · 大约 ' + Math.max(1, Math.round(today.length * 0.4)) + ' 分钟'
                : '明天会有新的到期卡。现在可以写几张新卡，或者去做错题。'}
            </p>
          </div>
          {today.length > 0 ? (
            <Button variant="primary" icon={<Play />} onClick={() => setSession(today)}>
              开始复习
            </Button>
          ) : (
            <Button variant="secondary" onClick={() => navigate('/wrong-questions')}>
              去看错题
            </Button>
          )}
        </section>
      ) : null}

      {deck.isError ? (
        <Notice tone="danger" title="卡组没能加载" actions={<Button size="sm" onClick={() => void deck.refetch()}>重试</Button>}>
          确认本地学习服务已经启动。
        </Notice>
      ) : !loading && cards.length === 0 ? (
        <Empty
          icon={<Layers />}
          title="还没有记忆卡"
          body="好的卡片一张只考一件事。可以自己写，也可以把讲义贴给 AI，让它按这个原则出卡。"
          actions={
            <>
              <Button variant="primary" icon={<Plus />} onClick={() => setEditing({ card: null })}>
                写第一张卡
              </Button>
              <Button variant="secondary" icon={<Sparkles />} onClick={() => setGenerating(true)}>
                AI 出卡
              </Button>
              <Button variant="ghost" icon={<MessageSquareText />} onClick={() => navigate('/?ask=帮我把最近学的内容整理成几张一问一答的记忆卡，先给我草案')}>
                问教练
              </Button>
            </>
          }
        />
      ) : (
        !loading && (
          <section aria-labelledby="deck-title">
            <div className={s.deckHead}>
              <h2 id="deck-title" className={s.deckTitle}>
                卡组
              </h2>
              <Segmented
                ariaLabel="按状态筛选"
                size="sm"
                value={filter}
                onChange={v => {
                  setFilter(v)
                  setShown(PAGE)
                }}
                options={[
                  { value: 'all', label: `全部 ${counts.total}` },
                  { value: 'due', label: `到期 ${counts.due}` },
                  { value: 'new', label: `新卡 ${counts.new}` },
                  { value: 'learning', label: `学习中 ${counts.learning}` },
                  { value: 'mature', label: `熟练 ${counts.mature}` },
                ]}
              />
              <div className={s.deckTools}>
                <Input
                  wrapperClassName={s.deckSearch}
                  size="sm"
                  prefix={<Search />}
                  placeholder="搜索卡片内容"
                  aria-label="搜索卡片"
                  value={query}
                  onChange={e => {
                    setQuery(e.target.value)
                    setShown(PAGE)
                  }}
                  suffix={
                    query ? (
                      <IconButton label="清除" size="sm" noTooltip onClick={() => setQuery('')}>
                        <X />
                      </IconButton>
                    ) : undefined
                  }
                />
              </div>
            </div>

            {tags.length > 0 && (
              <div className={s.tags} role="group" aria-label="按标签筛选">
                {tags.map(t => (
                  <Chip key={t.tag} selected={tag === t.tag} onClick={() => setTag(v => (v === t.tag ? null : t.tag))}>
                    #{t.tag} {t.count}
                  </Chip>
                ))}
              </div>
            )}

            {filtered.length === 0 ? (
              <Empty
                icon={<Search />}
                title="没有符合条件的卡片"
                body="换一个筛选条件看看。"
                actions={
                  <Button
                    size="sm"
                    variant="secondary"
                    onClick={() => {
                      setFilter('all')
                      setTag(null)
                      setQuery('')
                    }}
                  >
                    清除筛选
                  </Button>
                }
              />
            ) : (
              <ul className={s.deck}>
                {filtered.slice(0, shown).map(c => {
                  const st = stateOf(c)
                  return (
                    <li key={c.id} className={s.row}>
                      <span className={s.rowFront} title={c.front}>
                        {c.front}
                      </span>
                      <span className={s.rowBack} title={c.back}>
                        {c.back}
                      </span>
                      <span className={s.rowState}>
                        <Badge tone={STATE_META[st].tone}>{STATE_META[st].label}</Badge>
                        <span>{scheduleLabel(c)}</span>
                      </span>
                      <span className={s.rowActions}>
                        <IconButton label="编辑" size="sm" onClick={() => setEditing({ card: c })}>
                          <Pencil />
                        </IconButton>
                        <IconButton label="删除" size="sm" onClick={() => setRemoving(c)}>
                          <Trash2 />
                        </IconButton>
                      </span>
                    </li>
                  )
                })}
                {filtered.length > shown && (
                  <li className={s.more}>
                    <Button size="sm" variant="ghost" onClick={() => setShown(n => n + PAGE)}>
                      再显示 {Math.min(PAGE, filtered.length - shown)} 张
                    </Button>
                  </li>
                )}
              </ul>
            )}
            {cards.length >= DECK_LIMIT && (
              <p className={s.lead} style={{ marginTop: '0.75rem', fontSize: 'var(--mx-type-caption)', color: 'var(--mx-text-3)' }}>
                卡组里只显示最先到期的 {DECK_LIMIT} 张。
              </p>
            )}
          </section>
        )
      )}

      <CardDialog open={Boolean(editing)} onOpenChange={v => !v && setEditing(null)} card={editing?.card} onSaved={upsertLocal} />
      <GenerateDialog
        open={generating}
        onOpenChange={setGenerating}
        onCreated={made => {
          qc.setQueryData<AnkiCardItem[]>(DECK_KEY, prev => [...made, ...(prev ?? [])])
          void qc.invalidateQueries({ queryKey: QUEUE_KEY })
        }}
      />
      <CsvDialog open={csvOpen} onOpenChange={setCsvOpen} onImported={refresh} />
      <Confirm
        open={Boolean(removing)}
        onOpenChange={v => !v && setRemoving(null)}
        tone="danger"
        title="删除这张卡？"
        description={removing ? `「${removing.front}」和它的复习记录会一起删除。` : undefined}
        confirmLabel="删除"
        onConfirm={async () => {
          if (!removing) return
          try {
            await deleteAnkiCard(removing.id)
            qc.setQueryData<AnkiCardItem[]>(DECK_KEY, prev => (prev ?? []).filter(c => c.id !== removing.id))
            void qc.invalidateQueries({ queryKey: QUEUE_KEY })
            toast.success('已删除')
          } catch (error) {
            toast.error(getApiErrorMessage(error, '删除失败'))
            throw error
          }
        }}
      />
    </div>
  )
}

