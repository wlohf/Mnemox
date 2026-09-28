import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, BookOpen, BookOpenCheck, Check, CircleX, Eye, Lightbulb, RotateCcw, Trash2 } from 'lucide-react'
import {
  Badge,
  Button,
  Confirm,
  Empty,
  IconButton,
  Kbd,
  Notice,
  ProgressBar,
  RadioCards,
  Segmented,
  Skeleton,
  Textarea,
  toast,
} from '../../ui'
import {
  completeReviewTask,
  deleteReviewTask,
  getReviewContent,
  listReviewTasks,
  submitReviewAnswers,
  type ReviewContent,
  type ReviewResult,
  type ReviewTaskItem,
} from '../../services/reviewApi'
import { listWrongQuestions, type WrongQuestionItem } from '../../services/wrongQuestionApi'
import { usePageChrome } from '../../app/shell/shellStore'
import { qk } from '../../app/queryClient'
import { Page, PageHeader } from '../../ui'
import { AnswerReveal, RecallGrades, gradeForKey, recallStyles } from './Recall'
import s from './review.module.css'

type Scope = 'due' | 'all'
type Kind = 'all' | 'question' | 'chapter'

const MASTERY: Record<string, { label: string; tone: 'danger' | 'warning' | 'success' }> = {
  not_mastered: { label: '未掌握', tone: 'danger' },
  partial: { label: '部分掌握', tone: 'warning' },
  mastered: { label: '已掌握', tone: 'success' },
}

function when(iso?: string | null) {
  if (!iso) return null
  const d = new Date(iso.endsWith('Z') || iso.includes('+') ? iso : `${iso}Z`)
  if (Number.isNaN(d.getTime())) return null
  return d
}

function relative(d: Date | null) {
  if (!d) return '—'
  const days = Math.round((d.getTime() - Date.now()) / 86_400_000)
  if (days === 0) return '今天'
  if (days < 0) return `逾期 ${-days} 天`
  return `${days} 天后`
}

export function ReviewPage() {
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const coachAttemptId = params.get('coach_attempt')?.trim() || null
  const qc = useQueryClient()
  const [scope, setScope] = useState<Scope>('due')
  const [kind, setKind] = useState<Kind>('all')
  const [session, setSession] = useState<ReviewTaskItem[] | null>(null)
  const [removing, setRemoving] = useState<ReviewTaskItem | null>(null)
  const tasks = useQuery({ queryKey: qk.reviewTasks(scope, kind), queryFn: () => listReviewTasks(scope, kind) })
  const wrong = useQuery({ queryKey: qk.wrongQuestions, queryFn: () => listWrongQuestions(), staleTime: 60_000 })

  usePageChrome({ title: '复习' })

  const list = tasks.data ?? []
  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ['review'] })
    void qc.invalidateQueries({ queryKey: qk.dashboard })
    void qc.invalidateQueries({ queryKey: qk.wrongQuestions })
  }

  if (session) {
    return (
      <Page width="narrow">
        <ReviewSession
          queue={session}
          wrongById={new Map((wrong.data ?? []).map(w => [w.id, w]))}
          coachAttemptId={coachAttemptId}
          onExit={() => {
            setSession(null)
            refresh()
            if (coachAttemptId) navigate('/review', { replace: true })
          }}
        />
      </Page>
    )
  }

  const due = list.filter(t => (when(t.next_review_at ?? t.scheduled_date)?.getTime() ?? 0) <= Date.now() + 86_400_000)

  return (
    <Page width="reading">
      <PageHeader
        kicker={<><BookOpenCheck aria-hidden />主动回忆</>}
        title="复习"
        lead="先别看答案。用自己的话把记得的说出来，再对照答案给自己打分，间隔会据此调整。"
        actions={
          list.length > 0 && (
            <Button variant="primary" icon={<BookOpen />} onClick={() => setSession(scope === 'due' ? list : due.length ? due : list)}>
              开始复习 {scope === 'due' ? list.length : due.length || list.length} 项
            </Button>
          )
        }
      />

      {coachAttemptId && (
        <Notice tone="ink" icon={<Lightbulb />} title="这次复习来自教练的建议" className={s.toolbar}>
          完成一项复习后，结果会自动反馈给教练，用来调整之后的提醒。
        </Notice>
      )}

      <div className={s.toolbar}>
        <Segmented
          ariaLabel="范围"
          value={scope}
          onChange={setScope}
          options={[
            { value: 'due', label: '今天到期' },
            { value: 'all', label: '全部' },
          ]}
        />
        <Segmented
          ariaLabel="类型"
          size="sm"
          value={kind}
          onChange={setKind}
          options={[
            { value: 'all', label: '全部' },
            { value: 'question', label: '错题' },
            { value: 'chapter', label: '章节' },
          ]}
        />
        <span className={s.toolbarEnd}>
          <Badge tone="evidence">{list.length} 项</Badge>
        </span>
      </div>

      {tasks.isLoading ? (
        <div className={s.list}>
          {[0, 1, 2].map(i => (
            <div key={i} className={s.row}>
              <Skeleton width={32} height={32} radius={9} />
              <div>
                <Skeleton width="60%" height={14} />
                <Skeleton width="36%" height={11} style={{ marginTop: 8 }} />
              </div>
            </div>
          ))}
        </div>
      ) : tasks.isError ? (
        <Notice tone="danger" title="复习任务没能加载" actions={<Button size="sm" onClick={() => void tasks.refetch()}>重试</Button>}>
          确认本地学习服务已经启动。
        </Notice>
      ) : list.length === 0 ? (
        <Empty
          icon={<BookOpenCheck />}
          title={scope === 'due' ? '今天没有到期的复习' : '还没有复习任务'}
          body={
            scope === 'due'
              ? '间隔复习的节奏由你每次的打分决定。今天可以去巩固薄弱章节，或者做几张记忆卡。'
              : '答错的题和学完的章节会自动排进复习队列。'
          }
          actions={
            <>
              <Button variant="secondary" onClick={() => navigate('/anki')}>
                去做记忆卡
              </Button>
              <Button variant="ghost" onClick={() => navigate('/wrong-questions')}>
                打开错题本
              </Button>
            </>
          }
        />
      ) : (
        <ul className={s.list}>
          {list.map(t => {
            const next = when(t.next_review_at ?? t.scheduled_date)
            const overdue = next ? next.getTime() < Date.now() - 86_400_000 : false
            const m = MASTERY[t.mastery_status] ?? MASTERY.partial
            return (
              <li key={t.task_id} className={s.row}>
                <span className={s.rowIcon} data-kind={t.item_type} aria-hidden>
                  {t.item_type === 'chapter' ? <BookOpen /> : <CircleX />}
                </span>
                <div className={s.rowBody}>
                  <span className={s.rowTitle} title={t.content}>
                    {t.content}
                  </span>
                  <span className={s.rowMeta}>
                    <span>{t.item_type === 'chapter' ? '章节复习' : '错题复习'}</span>
                    {t.chapter_title && t.chapter_title !== t.content && <span>{t.chapter_title}</span>}
                    <Badge tone={m.tone}>{m.label}</Badge>
                    {t.item_type === 'chapter' && typeof t.chapter_mastery_level === 'number' && (
                      <span>掌握度 {Math.round(t.chapter_mastery_level)}%</span>
                    )}
                    {t.wrong_count > 0 && <span>错过 {t.wrong_count} 次</span>}
                    <span data-overdue={overdue || undefined}>{relative(next)}</span>
                  </span>
                </div>
                <span className={s.rowActions}>
                  <Button size="sm" variant="secondary" onClick={() => setSession([t])}>
                    复习
                  </Button>
                  <IconButton label="移出复习队列" size="sm" onClick={() => setRemoving(t)}>
                    <Trash2 />
                  </IconButton>
                </span>
              </li>
            )
          })}
        </ul>
      )}

      <Confirm
        open={!!removing}
        onOpenChange={v => !v && setRemoving(null)}
        tone="danger"
        title="把这一项移出复习队列？"
        description="移出后它不会再按间隔提醒你。错题本身和学习记录都会保留。"
        confirmLabel="移出"
        onConfirm={async () => {
          if (!removing) return
          const ok = await deleteReviewTask(removing.task_id)
          if (!ok) {
            toast.error('移出失败，请稍后重试')
            throw new Error('delete failed')
          }
          toast.success('已移出复习队列')
          refresh()
        }}
      />
    </Page>
  )
}

/* ============================================================================
   Session — one item at a time
   ========================================================================== */
function ReviewSession({
  queue,
  wrongById,
  coachAttemptId,
  onExit,
}: {
  queue: ReviewTaskItem[]
  wrongById: Map<number, WrongQuestionItem>
  coachAttemptId: string | null
  onExit: () => void
}) {
  const [index, setIndex] = useState(0)
  const [results, setResults] = useState<number[]>([])
  const current = queue[index]
  const finished = index >= queue.length

  const advance = (quality?: number) => {
    if (quality !== undefined) setResults(r => [...r, quality])
    setIndex(i => i + 1)
  }

  if (finished) {
    const remembered = results.filter(q => q >= 4).length
    return (
      <div className={s.card}>
        <div className={s.done}>
          <span className={s.doneSeal}>
            <Check aria-hidden />
            已完成
          </span>
          <h2 className={s.doneTitle}>这一轮复习做完了</h2>
          <p className={s.doneBody}>
            {results.length > 0
              ? `${results.length} 项里有 ${remembered} 项想起来了。没想起来的会更早出现，这正是间隔复习起作用的方式。`
              : '复习结果已经记录，下一次复习时间已按你的表现调整。'}
          </p>
          <Button variant="primary" onClick={onExit}>
            返回复习列表
          </Button>
        </div>
      </div>
    )
  }

  return (
    <div className={s.session}>
      <div className={s.progressRow}>
        <IconButton label="结束本轮复习" onClick={onExit}>
          <ArrowLeft />
        </IconButton>
        <ProgressBar className={s.progressBar} value={index / queue.length} label="复习进度" color="var(--mx-evidence)" />
        <span className={s.progressLabel}>
          {index + 1} / {queue.length}
        </span>
      </div>
      {current.item_type === 'chapter' ? (
        <ChapterReview key={current.task_id} task={current} coachAttemptId={coachAttemptId} onDone={() => advance()} />
      ) : (
        <QuestionReview
          key={current.task_id}
          task={current}
          wrong={wrongById.get(current.item_id)}
          coachAttemptId={coachAttemptId}
          onGraded={advance}
        />
      )}
    </div>
  )
}

function QuestionReview({
  task,
  wrong,
  coachAttemptId,
  onGraded,
}: {
  task: ReviewTaskItem
  wrong?: WrongQuestionItem
  coachAttemptId: string | null
  onGraded: (q: number) => void
}) {
  const [attempt, setAttempt] = useState('')
  const [revealed, setRevealed] = useState(false)
  const [saving, setSaving] = useState(false)
  const m = MASTERY[task.mastery_status] ?? MASTERY.partial

  const grade = async (quality: number) => {
    setSaving(true)
    try {
      await completeReviewTask(task.task_id, quality, coachAttemptId)
      onGraded(quality)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : '保存失败，请重试')
    } finally {
      setSaving(false)
    }
  }

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement
      if (target.tagName === 'TEXTAREA' || target.tagName === 'INPUT') {
        if (e.key === 'Enter' && (e.ctrlKey || e.metaKey) && !revealed) setRevealed(true)
        return
      }
      if (!revealed && (e.key === ' ' || e.key === 'Enter')) {
        e.preventDefault()
        setRevealed(true)
      } else if (revealed && !saving) {
        const g = gradeForKey(e.key)
        if (g) void grade(g.quality)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  })

  return (
    <article className={s.card} aria-live="polite">
      <div className={s.cardTop}>
        <Badge tone="evidence" icon={<CircleX />}>
          错题
        </Badge>
        {task.chapter_title && <Badge>{task.chapter_title}</Badge>}
        <Badge tone={m.tone}>{m.label}</Badge>
        {task.wrong_count > 0 && <span className={s.cardTopEnd}>错过 {task.wrong_count} 次</span>}
      </div>
      <h2 className={s.question}>{task.content}</h2>
      {!revealed ? (
        <>
          <p className={s.recallHint}>先在心里（或下面）回答一遍。说不出来也没关系，那正好暴露了需要补的地方。</p>
          <div className={s.attempt}>
            <Textarea
              reading
              autoGrow
              maxHeight={240}
              value={attempt}
              onChange={e => setAttempt(e.target.value)}
              placeholder="写下你的回答（可选）"
              aria-label="我的回答"
            />
          </div>
          <div className={s.actions}>
            <Button variant="primary" icon={<Eye />} onClick={() => setRevealed(true)}>
              显示答案
            </Button>
            <span className={s.spacer} />
            <span className={s.keyHint}>
              按 <Kbd>空格</Kbd> 显示答案
            </span>
          </div>
        </>
      ) : (
        <>
          <AnswerReveal answer={wrong?.answer} explanation={wrong?.explanation} />
          <RecallGrades disabled={saving} onGrade={q => void grade(q)} />
        </>
      )}
    </article>
  )
}

type ChapterStep = 'loading' | 'summary' | 'questions' | 'result'

function ChapterReview({
  task,
  coachAttemptId,
  onDone,
}: {
  task: ReviewTaskItem
  coachAttemptId: string | null
  onDone: () => void
}) {
  const [step, setStep] = useState<ChapterStep>('loading')
  const [content, setContent] = useState<ReviewContent | null>(null)
  const [answers, setAnswers] = useState<Record<number, string>>({})
  const [result, setResult] = useState<ReviewResult | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    getReviewContent(task.task_id)
      .then(c => {
        if (cancelled) return
        setContent(c)
        setStep('summary')
      })
      .catch(e => !cancelled && setError(e instanceof Error ? e.message : '复习内容生成失败'))
    return () => {
      cancelled = true
    }
  }, [task.task_id])

  const allAnswered = useMemo(() => (content?.questions ?? []).every(q => (answers[q.id] ?? '').trim()), [answers, content])

  const submit = async () => {
    if (!content) return
    setSubmitting(true)
    try {
      const r = await submitReviewAnswers(task.task_id, {
        answers: content.questions.map(q => ({ question: q.question, answer: answers[q.id] || '' })),
        coach_action_attempt_id: coachAttemptId,
      })
      setResult(r)
      setStep('result')
    } catch (e) {
      toast.error(e instanceof Error ? e.message : '提交失败')
    } finally {
      setSubmitting(false)
    }
  }

  if (error) {
    return (
      <div className={s.card}>
        <Notice tone="danger" title="这次章节复习没能生成" actions={<Button size="sm" onClick={onDone}>跳过</Button>}>
          {error}。可能是还没有配置 AI 模型，或者资料内容不足以出题。
        </Notice>
      </div>
    )
  }

  return (
    <article className={s.card}>
      <div className={s.cardTop}>
        <Badge tone="ink" icon={<BookOpen />}>
          章节复习
        </Badge>
        {typeof task.chapter_mastery_level === 'number' && <Badge>掌握度 {Math.round(task.chapter_mastery_level)}%</Badge>}
        <span className={s.cardTopEnd}>{step === 'questions' ? '检验' : step === 'result' ? '结果' : '回顾要点'}</span>
      </div>
      <h2 className={s.question}>{task.content}</h2>

      {step === 'loading' && (
        <div style={{ marginTop: 20, display: 'flex', flexDirection: 'column', gap: 10 }} aria-busy="true" aria-label="正在生成复习内容">
          <Skeleton height={16} />
          <Skeleton height={16} width="86%" />
          <Skeleton height={16} width="70%" />
        </div>
      )}

      {step === 'summary' && content && (
        <>
          <p className={s.recallHint}>先读一遍要点。读完之后会有几道题检验你是不是真的记住了。</p>
          <ol className={s.points} style={{ marginTop: 16 }}>
            {content.summary.map(p => (
              <li key={p} className={s.point}>
                {p}
              </li>
            ))}
          </ol>
          <div className={s.actions}>
            <Button variant="primary" onClick={() => setStep('questions')}>
              开始答题（{content.questions.length} 题）
            </Button>
          </div>
        </>
      )}

      {step === 'questions' && content && (
        <>
          <div className={s.qList} style={{ marginTop: 18 }}>
            {content.questions.map((q, i) => (
              <div key={q.id} className={s.qItem}>
                <p className={s.qText}>
                  <span>{i + 1}.</span>
                  {q.question}
                </p>
                {q.type === 'choice' && q.options ? (
                  <RadioCards
                    ariaLabel={`第 ${i + 1} 题选项`}
                    value={answers[q.id] ?? ''}
                    onValueChange={v => setAnswers(a => ({ ...a, [q.id]: v }))}
                    options={q.options.map(opt => ({ value: opt.charAt(0), title: opt }))}
                  />
                ) : (
                  <Textarea
                    autoGrow
                    maxHeight={220}
                    value={answers[q.id] ?? ''}
                    onChange={e => setAnswers(a => ({ ...a, [q.id]: e.target.value }))}
                    placeholder="用自己的话回答"
                    aria-label={`第 ${i + 1} 题回答`}
                  />
                )}
              </div>
            ))}
          </div>
          <div className={s.actions}>
            <Button variant="ghost" icon={<RotateCcw />} onClick={() => setStep('summary')}>
              回看要点
            </Button>
            <span className={s.spacer} />
            <Button variant="primary" loading={submitting} disabled={!allAnswered} onClick={() => void submit()}>
              提交答案
            </Button>
          </div>
        </>
      )}

      {step === 'result' && result && (
        <>
          <div className={s.result} style={{ marginTop: 20 }}>
            <span className={s.score} data-band={result.score >= 80 ? 'good' : result.score >= 60 ? 'mid' : 'low'}>
              {result.score}
            </span>
            <div>
              <p className={recallStyles.answer} style={{ fontSize: 'var(--mx-type-body)' }}>
                {result.feedback}
              </p>
              <p className={s.recallHint} style={{ marginTop: 8 }}>
                掌握度评级 {result.quality}/5 · 下次复习{' '}
                {new Date(result.next_review_date).toLocaleDateString('zh-CN', { month: 'long', day: 'numeric' })}
              </p>
            </div>
          </div>
          <div className={s.actions}>
            <span className={s.spacer} />
            <Button variant="primary" onClick={onDone}>
              继续
            </Button>
          </div>
        </>
      )}
    </article>
  )
}
