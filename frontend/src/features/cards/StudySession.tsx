import { useEffect, useRef, useState, type CSSProperties } from 'react'
import { ArrowLeft, Check, RotateCcw } from 'lucide-react'
import { Badge, Button, IconButton, Kbd, ProgressBar, toast } from '../../ui'
import { reviewAnkiCard, type AnkiCardItem } from '../../services/ankiApi'
import { getApiErrorMessage } from '../../services/apiClient'
import { CARD_GRADES, STATE_META, scheduleLabel, stateOf, tagsOf } from './cardModel'
import s from './cards.module.css'

/*
 * One card at a time. Space (or a click) turns the card over; 1–4 grade it.
 * A graded card slides off before the next arrives, and the session ends
 * with a tally of how it went.
 */

interface Result {
  quality: number
  next: AnkiCardItem
}

export function StudySession({ queue, onExit }: { queue: AnkiCardItem[]; onExit: (reviewed: number) => void }) {
  const [index, setIndex] = useState(0)
  const [flipped, setFlipped] = useState(false)
  const [saving, setSaving] = useState(false)
  const [leaving, setLeaving] = useState(false)
  const [results, setResults] = useState<Result[]>([])
  const cardRef = useRef<HTMLDivElement | null>(null)
  const current = queue[index]
  const finished = index >= queue.length

  useEffect(() => {
    cardRef.current?.focus({ preventScroll: true })
  }, [index])

  const grade = async (quality: number) => {
    if (!current || saving) return
    setSaving(true)
    try {
      const next = await reviewAnkiCard(current.id, quality)
      if (!next) throw new Error('这次复习没有保存成功')
      setResults(r => [...r, { quality, next }])
      setLeaving(true)
      window.setTimeout(
        () => {
          setLeaving(false)
          setFlipped(false)
          setIndex(i => i + 1)
        },
        window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 0 : 280,
      )
    } catch (error) {
      toast.error(getApiErrorMessage(error, '保存失败，请重试'))
    } finally {
      setSaving(false)
    }
  }

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (finished) return
      const t = e.target as HTMLElement
      if (/^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName) || t.isContentEditable) return
      if (!flipped && (e.key === ' ' || e.key === 'Enter')) {
        e.preventDefault()
        setFlipped(true)
      } else if (flipped && !saving && !leaving) {
        const g = CARD_GRADES.find(x => x.hotkey === e.key)
        if (g) {
          e.preventDefault()
          void grade(g.quality)
        }
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  })

  if (finished) {
    const remembered = results.filter(r => r.quality >= 4).length
    const again = results.filter(r => r.quality < 3).length
    return (
      <div className={s.session}>
        <div className={s.done}>
          <span className={s.seal}>
            <Check aria-hidden />
            今日已毕
          </span>
          <h2 className={s.doneTitle}>这一轮做完了</h2>
          <p className={s.doneBody}>
            {again > 0
              ? `有 ${again} 张忘了，它们会比别的卡更早回来。这不是退步，是间隔复习在帮你把薄弱的地方补牢。`
              : '每一张都想起来了。间隔会按你的表现拉长，下次见面会更晚一些。'}
          </p>
          <ul className={s.tally}>
            <li>
              <b>{results.length}</b>
              复习
            </li>
            <li style={{ '--tally': 'var(--mx-success)' } as CSSProperties}>
              <b>{remembered}</b>
              记得
            </li>
            <li style={{ '--tally': 'var(--mx-danger)' } as CSSProperties}>
              <b>{again}</b>
              忘了
            </li>
          </ul>
          <Button variant="primary" onClick={() => onExit(results.length)}>
            回到卡组
          </Button>
        </div>
      </div>
    )
  }

  const state = stateOf(current)
  const tags = tagsOf(current)
  return (
    <div className={s.session}>
      <div className={s.progressRow}>
        <IconButton label="结束本轮" onClick={() => onExit(results.length)}>
          <ArrowLeft />
        </IconButton>
        <ProgressBar className={s.progressBar} value={index / queue.length} label="本轮进度" />
        <span className={s.progressLabel}>
          {index + 1} / {queue.length}
        </span>
      </div>

      <div className={s.stage}>
        <div
          ref={cardRef}
          key={current.id}
          className={`${s.card} ${leaving ? s.leave : s.enter}`}
          data-flipped={flipped || undefined}
          role="button"
          tabIndex={0}
          aria-label={flipped ? '卡片背面' : '卡片正面，按空格翻面'}
          aria-live="polite"
          onClick={() => !flipped && setFlipped(true)}
        >
          <div className={s.face} aria-hidden={flipped}>
            <div className={s.faceTop}>
              <Badge tone={STATE_META[state].tone}>{STATE_META[state].label}</Badge>
              {tags.slice(0, 3).map(t => (
                <span key={t}>#{t}</span>
              ))}
              <span>{current.source === 'ai' ? 'AI 生成' : '手写'}</span>
            </div>
            <div className={s.faceBody}>
              <p className={s.front}>{current.front}</p>
            </div>
            <div className={s.faceHint}>
              先在心里回答，再按 <Kbd>空格</Kbd> 翻面
            </div>
          </div>
          <div className={`${s.face} ${s.back}`} aria-hidden={!flipped}>
            <div className={s.faceTop}>
              <span>答案</span>
              <span>{scheduleLabel(current)}</span>
            </div>
            <div className={s.faceBody}>
              <div>
                <p className={s.answerFront}>{current.front}</p>
                <p className={s.answer}>{current.back}</p>
                {current.note && <p className={s.note}>{current.note}</p>}
              </div>
            </div>
          </div>
        </div>
      </div>

      {flipped ? (
        <div className={s.grades} role="group" aria-label="这张卡记得多少">
          {CARD_GRADES.map(g => (
            <button key={g.key} type="button" className={s.grade} data-g={g.key} disabled={saving || leaving} onClick={() => void grade(g.quality)}>
              <span className={s.gradeTop}>
                {g.label}
                <Kbd>{g.hotkey}</Kbd>
              </span>
              <span className={s.gradeHint}>{g.hint}</span>
            </button>
          ))}
        </div>
      ) : (
        <div className={s.flipRow}>
          <Button variant="secondary" icon={<RotateCcw />} onClick={() => setFlipped(true)}>
            翻面看答案
          </Button>
        </div>
      )}
    </div>
  )
}
