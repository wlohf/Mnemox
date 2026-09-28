import { useEffect, useMemo, useRef, useState, type CSSProperties } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  BookOpenCheck,
  CalendarClock,
  ChevronDown,
  CircleX,
  Eye,
  Layers,
  MessageSquareText,
  MoreHorizontal,
  Plus,
  RotateCcw,
  Search,
  Trash2,
  X,
} from 'lucide-react'
import {
  Button,
  Confirm,
  Dialog,
  Empty,
  Field,
  IconButton,
  Input,
  Kbd,
  Menu,
  Notice,
  Select,
  Skeleton,
  Slider,
  Textarea,
  toast,
} from '../../ui'
import {
  createWrongQuestion,
  deleteWrongQuestion,
  listWrongQuestions,
  reviewWrongQuestion,
  updateWrongQuestion,
  type WrongQuestionItem,
} from '../../services/wrongQuestionApi'
import { createAnkiCard } from '../../services/ankiApi'
import { usePageChrome } from '../../app/shell/shellStore'
import { qk } from '../../app/queryClient'
import { dueLabel } from '../../lib/dates'
import { AnswerReveal, RecallGrades, gradeForKey, recallDifficulty, RECALL_GRADES } from '../review/Recall'
import {
  QUESTION_TYPES,
  SORTS,
  STATUS_META,
  STATUS_ORDER,
  cardBack,
  countByStatus,
  excerpt,
  filterItems,
  isDue,
  questionTypeLabel,
  sortItems,
  statusOf,
  type MasteryStatus,
  type SortKey,
  type StatusFilter,
} from './wrongModel'
import s from './wrong.module.css'

/*
 * The wrong-question list is fetched once in full (the API pages at 200) and
 * filtered locally, so the summary always describes the whole book, not the
 * current filter.
 */
const PAGE = 200

async function fetchAll(): Promise<WrongQuestionItem[]> {
  return listWrongQuestions()
}

export function WrongQuestionsPage() {
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [params, setParams] = useSearchParams()
  const [status, setStatus] = useState<StatusFilter>('all')
  const [query, setQuery] = useState(() => params.get('q') ?? '')
  const [sort, setSort] = useState<SortKey>('due')
  const [openId, setOpenId] = useState<number | null>(null)
  const [creating, setCreating] = useState(false)
  const [removing, setRemoving] = useState<WrongQuestionItem | null>(null)
  const searchRef = useRef<HTMLInputElement | null>(null)

  // A search handed over in the URL (e.g. a weak point in the report) fills
  // the box once, then leaves the URL clean so reloads don't re-apply it.
  useEffect(() => {
    const q = params.get('q')
    if (q === null) return
    setQuery(q)
    setStatus('all')
    const next = new URLSearchParams(params)
    next.delete('q')
    setParams(next, { replace: true })
  }, [params, setParams])

  const list = useQuery({ queryKey: qk.wrongQuestions, queryFn: fetchAll, staleTime: 30_000 })
  const items = list.data ?? []

  const counts = useMemo(() => countByStatus(items), [items])
  const dueItems = useMemo(() => items.filter(it => isDue(it) && statusOf(it) !== 'mastered'), [items])
  const shown = useMemo(() => sortItems(filterItems(items, status, query), sort), [items, status, query, sort])

  usePageChrome({ title: '错题本' })

  // "/" focuses search, like the rest of the app's lists.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement
      if (e.key === '/' && !/^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName) && !t.isContentEditable) {
        e.preventDefault()
        searchRef.current?.focus()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  const refresh = async () => {
    await qc.invalidateQueries({ queryKey: qk.wrongQuestions })
    void qc.invalidateQueries({ queryKey: ['review'] })
    void qc.invalidateQueries({ queryKey: qk.dashboard })
  }

  /** Swap one item in the cache so the list reacts instantly. */
  const patchCache = (next: WrongQuestionItem) => {
    qc.setQueryData<WrongQuestionItem[]>(qk.wrongQuestions, prev => (prev ?? []).map(it => (it.id === next.id ? next : it)))
  }

  const total = items.length
  const filtered = status !== 'all' || query.trim().length > 0

  return (
    <div className={s.page}>
      <header className={s.ledger}>
        <div className={s.ledgerText}>
          <h1 className={s.ledgerTitle}>错题本</h1>
          <p className={s.ledgerLead}>
            {total === 0 ? (
              '做错的题会记在这里，并按间隔复习的节奏回来找你。'
            ) : (
              <>
                共 <strong>{total}</strong> 道，<strong>{counts.not_mastered + counts.partial}</strong> 道还没吃透
                {dueItems.length > 0 && (
                  <>
                    ，其中 <strong>{dueItems.length}</strong> 道今天该复习了
                  </>
                )}
                。
              </>
            )}
          </p>
        </div>
        <div className={s.ledgerActions}>
          <Button variant="secondary" icon={<Plus />} onClick={() => setCreating(true)}>
            记一道错题
          </Button>
        </div>
      </header>

      {total > 0 && <Spectrum counts={counts} total={total} active={status} onPick={setStatus} />}

      {dueItems.length > 0 && status === 'all' && !query && (
        <div className={s.due} role="status">
          <span className={s.dueGlyph} aria-hidden>
            <CalendarClock />
          </span>
          <p className={s.dueText}>
            <strong>{dueItems.length} 道错题到了复习时间</strong>
            在复习里一题一题做：先回忆，再看答案，给自己打分。
          </p>
          <Button variant="primary" size="sm" icon={<BookOpenCheck />} onClick={() => navigate('/review')}>
            开始复习
          </Button>
        </div>
      )}

      {total > 0 && (
        <div className={s.toolbar}>
          <Input
            ref={searchRef}
            wrapperClassName={s.search}
            size="sm"
            prefix={<Search />}
            placeholder="搜索题目、答案或知识点"
            aria-label="搜索错题"
            value={query}
            onChange={e => setQuery(e.target.value)}
            suffix={
              query ? (
                <IconButton label="清除搜索" size="sm" noTooltip onClick={() => setQuery('')}>
                  <X />
                </IconButton>
              ) : (
                <Kbd>/</Kbd>
              )
            }
          />
          <div className={s.toolbarEnd}>
            <Select className={s.sortSelect} size="sm" ariaLabel="排序" value={sort} onValueChange={v => setSort(v as SortKey)} options={SORTS} />
          </div>
        </div>
      )}

      {list.isLoading ? (
        <div className={s.skel} aria-busy="true" aria-label="正在加载错题">
          {[0, 1, 2].map(i => (
            <div key={i} className={s.skelRow}>
              <Skeleton width={36} height={36} radius={18} />
              <div>
                <Skeleton width="72%" height={15} />
                <Skeleton width="40%" height={11} style={{ marginTop: 10 }} />
              </div>
            </div>
          ))}
        </div>
      ) : list.isError ? (
        <Notice tone="danger" title="错题没能加载" actions={<Button size="sm" onClick={() => void list.refetch()}>重试</Button>}>
          确认本地学习服务已经启动。
        </Notice>
      ) : total === 0 ? (
        <div className={s.empty}>
          <Empty
            icon={<CircleX />}
            title="错题本还是空的"
            body="练习、复习或和教练对话时答错的题会自动记在这里。也可以把作业和考试里的错题手动记下来。"
            actions={
              <>
                <Button variant="primary" icon={<Plus />} onClick={() => setCreating(true)}>
                  记一道错题
                </Button>
                <Button variant="ghost" icon={<MessageSquareText />} onClick={() => navigate('/?ask=根据我的资料出 5 道题考考我')}>
                  让教练出题
                </Button>
              </>
            }
          />
        </div>
      ) : shown.length === 0 ? (
        <Empty
          icon={<Search />}
          title={filtered ? '没有符合条件的错题' : '没有错题'}
          body={query ? `没找到包含「${query.trim()}」的题目。` : '换一个状态看看。'}
          actions={
            <Button
              variant="secondary"
              onClick={() => {
                setQuery('')
                setStatus('all')
              }}
            >
              清除筛选
            </Button>
          }
        />
      ) : (
        <ul className={s.list} aria-label="错题">
          {shown.map((it, i) => (
            <WrongItem
              key={it.id}
              index={i}
              item={it}
              open={openId === it.id}
              onToggle={() => setOpenId(v => (v === it.id ? null : it.id))}
              onUpdated={patchCache}
              onRemove={() => setRemoving(it)}
              onAfterGrade={() => void refresh()}
            />
          ))}
        </ul>
      )}

      {total >= PAGE && (
        <p className={s.hint} style={{ marginTop: '1rem', textAlign: 'center' }}>
          只显示最近的 {PAGE} 道错题。
        </p>
      )}

      <CreateDialog
        open={creating}
        onOpenChange={setCreating}
        onCreated={async created => {
          qc.setQueryData<WrongQuestionItem[]>(qk.wrongQuestions, prev => [created, ...(prev ?? [])])
          setStatus('all')
          setQuery('')
          setOpenId(created.id)
          await refresh()
        }}
      />

      <Confirm
        open={Boolean(removing)}
        onOpenChange={v => !v && setRemoving(null)}
        tone="danger"
        title="删除这道错题？"
        description="它的复习安排也会一起删除，之后不会再提醒你复习它。"
        confirmLabel="删除"
        onConfirm={async () => {
          if (!removing) return
          const ok = await deleteWrongQuestion(removing.id)
          if (!ok) {
            toast.error('删除失败，请稍后重试')
            throw new Error('delete failed')
          }
          qc.setQueryData<WrongQuestionItem[]>(qk.wrongQuestions, prev => (prev ?? []).filter(x => x.id !== removing.id))
          if (openId === removing.id) setOpenId(null)
          toast.success('已删除')
          await refresh()
        }}
      />
    </div>
  )
}

/* ============================================================================
   Spectrum — the whole book in one bar; each status is also a filter
   ========================================================================== */
function Spectrum({
  counts,
  total,
  active,
  onPick,
}: {
  counts: Record<MasteryStatus, number>
  total: number
  active: StatusFilter
  onPick: (f: StatusFilter) => void
}) {
  const present = STATUS_ORDER.filter(k => counts[k] > 0)
  const cols = present.map(k => `${counts[k]}fr`).join(' ')
  return (
    <>
      <div className={s.spectrum} style={{ '--cols': cols } as CSSProperties} role="img" aria-label={present.map(k => `${STATUS_META[k].label} ${counts[k]}`).join('，')}>
        {present.map((k, i) => (
          <span key={k} className={s.spectrumSeg} style={{ '--seg': STATUS_META[k].color, '--i': i } as CSSProperties} />
        ))}
      </div>
      <div className={s.legend} role="group" aria-label="按掌握程度筛选">
        <button type="button" className={s.legendItem} aria-pressed={active === 'all'} onClick={() => onPick('all')}>
          全部 <b>{total}</b>
        </button>
        {STATUS_ORDER.map(k => (
          <button
            key={k}
            type="button"
            className={s.legendItem}
            aria-pressed={active === k}
            style={{ '--seg': STATUS_META[k].color } as CSSProperties}
            onClick={() => onPick(active === k ? 'all' : k)}
          >
            <i aria-hidden />
            {STATUS_META[k].label} <b>{counts[k]}</b>
          </button>
        ))}
      </div>
    </>
  )
}

/* ============================================================================
   One wrong question — collapsed as a ledger line, expanded as practice
   ========================================================================== */
function WrongItem({
  item,
  index,
  open,
  onToggle,
  onUpdated,
  onRemove,
  onAfterGrade,
}: {
  item: WrongQuestionItem
  index: number
  open: boolean
  onToggle: () => void
  onUpdated: (next: WrongQuestionItem) => void
  onRemove: () => void
  onAfterGrade: () => void
}) {
  const navigate = useNavigate()
  const st = statusOf(item)
  const meta = STATUS_META[st]
  const due = st === 'mastered' ? null : dueLabel(item.next_review_at)
  const bodyId = `wq-${item.id}`
  // Mount practice on first open and keep it, so closing animates and a draft answer survives.
  const [mounted, setMounted] = useState(open)
  useEffect(() => {
    if (open) setMounted(true)
  }, [open])

  const menu = [
    {
      key: 'ask',
      label: '问教练这道题',
      icon: <MessageSquareText />,
      onSelect: () =>
        navigate(`/?${new URLSearchParams({ ask: '这道题我为什么会错？请先追问我的思路，再讲清楚。', context: excerpt(item.content, 80) })}`),
    },
    {
      key: 'card',
      label: '做成记忆卡',
      icon: <Layers />,
      onSelect: async () => {
        const card = await createAnkiCard({
          front: item.content,
          back: cardBack(item),
          tags: ['错题', item.knowledge_point ?? ''].filter(Boolean).join(','),
          note: item.chapter_title && item.chapter_title !== '未分类' ? item.chapter_title : undefined,
        })
        if (card) toast.success('已做成记忆卡', { actions: [{ label: '去看看', onClick: () => navigate('/anki') }] })
        else toast.error('没能创建记忆卡')
      },
    },
    { key: 'sep', type: 'separator' as const },
    { key: 'delete', label: '删除', icon: <Trash2 />, tone: 'danger' as const, onSelect: onRemove },
  ]

  return (
    <li className={s.item} data-open={open || undefined} style={{ '--i': index } as CSSProperties}>
      <div className={s.top}>
        <button type="button" className={s.head} aria-expanded={open} aria-controls={bodyId} onClick={onToggle}>
          <span className={s.mark} style={{ '--mark-color': meta.color } as CSSProperties}>
            <span className={s.markNum} aria-label={`错了 ${item.wrong_count} 次`}>
              {item.wrong_count}
            </span>
            <span className={s.markLabel}>次错</span>
          </span>
          <span className={s.headBody}>
            <span className={s.question}>{item.content}</span>
            <span className={s.meta}>
              <span className={s.statusText} style={{ color: meta.color }}>
                <i aria-hidden />
                {meta.label}
              </span>
              <span>{questionTypeLabel(item.question_type)}</span>
              {item.knowledge_point && <span className={s.kp}>#{item.knowledge_point}</span>}
              {item.chapter_title && item.chapter_title !== '未分类' && item.chapter_title !== item.knowledge_point && (
                <span>{item.chapter_title}</span>
              )}
              {item.review_count > 0 && <span>复习 {item.review_count} 次</span>}
              {due && (
                <span data-tone={due.tone === 'overdue' ? 'overdue' : due.tone === 'today' ? 'today' : undefined}>
                  <CalendarClock aria-hidden />
                  {due.tone === 'overdue' || due.tone === 'today' ? `该复习了 · ${due.text}` : `${due.text}复习`}
                </span>
              )}
            </span>
          </span>
        </button>
        <span className={s.headEnd}>
          <Menu
            items={menu}
            trigger={
              <IconButton label="更多操作" size="sm">
                <MoreHorizontal />
              </IconButton>
            }
          />
          <IconButton label={open ? '收起' : '展开练习'} size="sm" aria-expanded={open} aria-controls={bodyId} onClick={onToggle}>
            <ChevronDown className={s.chev} />
          </IconButton>
        </span>
      </div>
      <div
        className={s.body}
        id={bodyId}
        role="region"
        aria-label="练习这道题"
        aria-hidden={!open || undefined}
        ref={node => {
          // React 18's DOM types lack `inert`; set it directly so hidden practice can't take focus.
          if (node) (node as HTMLElement & { inert: boolean }).inert = !open
        }}
      >
        <div className={s.bodyInner}>{mounted && <Practice item={item} onUpdated={onUpdated} onAfterGrade={onAfterGrade} />}</div>
      </div>
    </li>
  )
}

function Practice({
  item,
  onUpdated,
  onAfterGrade,
}: {
  item: WrongQuestionItem
  onUpdated: (next: WrongQuestionItem) => void
  onAfterGrade: () => void
}) {
  const [attempt, setAttempt] = useState('')
  const [revealed, setRevealed] = useState(false)
  const [saving, setSaving] = useState(false)
  const [graded, setGraded] = useState<{ quality: number; next: WrongQuestionItem } | null>(null)
  const [statusBusy, setStatusBusy] = useState(false)
  const rootRef = useRef<HTMLDivElement | null>(null)
  const st = statusOf(item)

  const grade = async (quality: number) => {
    setSaving(true)
    try {
      const next = await reviewWrongQuestion(item.id, quality, recallDifficulty(quality))
      if (!next) throw new Error('复习记录没有保存成功')
      setGraded({ quality, next })
      onUpdated(next)
      onAfterGrade()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : '保存失败，请重试')
    } finally {
      setSaving(false)
    }
  }

  const setMastery = async (value: MasteryStatus) => {
    if (value === st) return
    setStatusBusy(true)
    try {
      const next = await updateWrongQuestion(item.id, { mastery_status: value })
      if (!next) throw new Error('更新失败')
      onUpdated(next)
      toast.success(`已标记为${STATUS_META[value].label}`)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : '更新失败')
    } finally {
      setStatusBusy(false)
    }
  }

  // Space reveals, 1–4 grade — only while focus is inside this card.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const root = rootRef.current
      if (!root || !root.contains(document.activeElement)) return
      const t = e.target as HTMLElement
      if (t.tagName === 'TEXTAREA' || t.tagName === 'INPUT') {
        if (e.key === 'Enter' && (e.ctrlKey || e.metaKey) && !revealed) {
          e.preventDefault()
          setRevealed(true)
        }
        return
      }
      if (!revealed && e.key === ' ' && t.tagName !== 'BUTTON') {
        e.preventDefault()
        setRevealed(true)
      } else if (revealed && !saving && !graded) {
        const g = gradeForKey(e.key)
        if (g) {
          e.preventDefault()
          void grade(g.quality)
        }
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  })

  const gradeInfo = graded ? RECALL_GRADES.find(g => g.quality === graded.quality) : undefined
  const nextDue = graded ? dueLabel(graded.next.next_review_at) : null

  return (
    <div className={s.practice} ref={rootRef}>
      {!revealed ? (
        <>
          <p className={s.hint}>先别看答案。把你现在会怎么答写下来，或者在心里过一遍。</p>
          <Textarea
            reading
            autoGrow
            rows={2}
            maxHeight={220}
            value={attempt}
            placeholder="我的回答（可选）"
            aria-label="我的回答"
            onChange={e => setAttempt(e.target.value)}
          />
          <div className={s.row}>
            <Button variant="primary" size="sm" icon={<Eye />} onClick={() => setRevealed(true)}>
              对答案
            </Button>
            <span className={s.spacer} />
            <span className={s.keyHint}>
              <Kbd>Ctrl</Kbd>
              <Kbd>Enter</Kbd> 对答案
            </span>
          </div>
        </>
      ) : (
        <>
          {attempt.trim() && (
            <p className={s.mine}>
              <strong>我的回答</strong>
              {attempt.trim()}
            </p>
          )}
          <AnswerReveal answer={item.answer} explanation={item.explanation} />
          {graded ? (
            <div className={s.graded} role="status">
              <span
                className={s.stamp}
                style={{ '--stamp': graded.quality >= 4 ? 'var(--mx-success)' : graded.quality >= 3 ? 'var(--mx-warning)' : 'var(--mx-danger)' } as CSSProperties}
              >
                {gradeInfo?.label ?? '已记录'}
              </span>
              <p className={s.gradedText}>
                已记录。现在是<strong>{STATUS_META[statusOf(graded.next)].label}</strong>
                {nextDue ? `，下次复习：${nextDue.text}` : ''}。
              </p>
              <span className={s.spacer} />
              <Button
                variant="ghost"
                size="sm"
                icon={<RotateCcw />}
                onClick={() => {
                  setGraded(null)
                  setRevealed(false)
                  setAttempt('')
                }}
              >
                再练一次
              </Button>
            </div>
          ) : (
            <RecallGrades disabled={saving} label="这次答对了吗" onGrade={q => void grade(q)} />
          )}
        </>
      )}

      <div className={s.tools}>
        <span className={s.toolsLabel}>直接标记</span>
        <span className={s.statusSet} role="group" aria-label="掌握程度">
          {STATUS_ORDER.map(k => (
            <button
              key={k}
              type="button"
              className={s.statusBtn}
              aria-pressed={st === k}
              disabled={statusBusy}
              style={{ '--seg': STATUS_META[k].color } as CSSProperties}
              onClick={() => void setMastery(k)}
            >
              <i aria-hidden />
              {STATUS_META[k].label}
            </button>
          ))}
        </span>
      </div>
    </div>
  )
}

/* ============================================================================
   Create — record a mistake from homework or an exam
   ========================================================================== */
const DIFFICULTY_LABEL = ['', '很简单', '简单', '中等', '难', '很难']

function CreateDialog({
  open,
  onOpenChange,
  onCreated,
}: {
  open: boolean
  onOpenChange: (v: boolean) => void
  onCreated: (item: WrongQuestionItem) => Promise<void>
}) {
  const [content, setContent] = useState('')
  const [type, setType] = useState('short_answer')
  const [difficulty, setDifficulty] = useState(2)
  const [answer, setAnswer] = useState('')
  const [explanation, setExplanation] = useState('')
  const [kp, setKp] = useState('')
  const [touched, setTouched] = useState(false)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (!open) return
    setContent('')
    setType('short_answer')
    setDifficulty(2)
    setAnswer('')
    setExplanation('')
    setKp('')
    setTouched(false)
  }, [open])

  const invalid = touched && !content.trim()
  const submit = async () => {
    setTouched(true)
    if (!content.trim()) return
    setBusy(true)
    try {
      const created = await createWrongQuestion({
        content: content.trim(),
        question_type: type,
        difficulty,
        answer: answer.trim() || undefined,
        explanation: explanation.trim() || undefined,
        knowledge_point: kp.trim() || undefined,
      })
      if (!created) throw new Error('没能保存这道错题')
      await onCreated(created)
      toast.success('已记进错题本', { description: '它已经排进今天的复习。' })
      onOpenChange(false)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : '保存失败')
    } finally {
      setBusy(false)
    }
  }

  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title="记一道错题"
      description="写下题目和正确答案。记下后它会马上排进复习，之后按你每次的表现调整间隔。"
      width={36}
      footer={
        <>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            取消
          </Button>
          <Button variant="primary" loading={busy} onClick={() => void submit()}>
            记下来
          </Button>
        </>
      }
    >
      <div className={s.form}>
        <Field label="题目" htmlFor="wq-content" error={invalid ? '题目不能为空' : undefined}>
          <Textarea
            id="wq-content"
            autoFocus
            reading
            autoGrow
            rows={3}
            maxHeight={240}
            value={content}
            invalid={invalid}
            placeholder="把题目原文贴进来"
            onChange={e => setContent(e.target.value)}
          />
        </Field>
        <div className={s.formRow}>
          <Field label="题型" htmlFor="wq-type">
            <Select id="wq-type" ariaLabel="题型" value={type} onValueChange={setType} options={QUESTION_TYPES} />
          </Field>
          <Field label="难度">
            <div className={s.difficulty}>
              <Slider ariaLabel="难度" min={1} max={5} step={1} value={difficulty} onValueChange={setDifficulty} />
              <span className={s.difficultyValue}>{DIFFICULTY_LABEL[difficulty]}</span>
            </div>
          </Field>
        </div>
        <Field label="正确答案" htmlFor="wq-answer" optional hint="复习时先回忆，再对照这里。">
          <Textarea id="wq-answer" autoGrow rows={2} maxHeight={200} value={answer} onChange={e => setAnswer(e.target.value)} />
        </Field>
        <Field label="为什么错 / 解析" htmlFor="wq-explain" optional>
          <Textarea
            id="wq-explain"
            autoGrow
            rows={2}
            maxHeight={200}
            value={explanation}
            placeholder="例如：把「识别」当成了「回忆」"
            onChange={e => setExplanation(e.target.value)}
          />
        </Field>
        <Field label="知识点" htmlFor="wq-kp" optional hint="填了之后会关联到掌握度里的同名概念。">
          <Input id="wq-kp" value={kp} placeholder="例如：费曼复盘" onChange={e => setKp(e.target.value)} />
        </Field>
      </div>
    </Dialog>
  )
}
