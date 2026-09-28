import { Kbd } from '../../ui'
import s from './recall.module.css'

/*
 * Shared active-recall UI. The same four grades drive 复习 and 错题本, so the
 * learner meets one vocabulary for "how well did I remember this".
 * Quality values follow the backend's 0–5 scale (SM-2 / FSRS input).
 */

export interface RecallGrade {
  key: 'again' | 'hard' | 'good' | 'easy'
  quality: number
  label: string
  body: string
  hotkey: string
}

export const RECALL_GRADES: readonly RecallGrade[] = [
  { key: 'again', quality: 1, label: '没想起来', body: '明天再来', hotkey: '1' },
  { key: 'hard', quality: 3, label: '勉强', body: '想了很久才对', hotkey: '2' },
  { key: 'good', quality: 4, label: '想起来了', body: '按计划推进', hotkey: '3' },
  { key: 'easy', quality: 5, label: '很轻松', body: '拉长间隔', hotkey: '4' },
]

/** Grade bound to a number key, if any. */
export function gradeForKey(key: string): RecallGrade | undefined {
  return RECALL_GRADES.find(g => g.hotkey === key)
}

/** Recall difficulty tag the wrong-question book stores next to a grade. */
export function recallDifficulty(quality: number): 'easy' | 'hard' | 'forgot' {
  if (quality >= 5) return 'easy'
  if (quality >= 3) return 'hard'
  return 'forgot'
}

export function RecallGrades({
  onGrade,
  disabled,
  label = '这次想起来了吗',
}: {
  onGrade: (quality: number) => void
  disabled?: boolean
  label?: string
}) {
  return (
    <div className={s.grades} role="group" aria-label={label}>
      {RECALL_GRADES.map(g => (
        <button key={g.key} type="button" className={s.grade} data-g={g.key} disabled={disabled} onClick={() => onGrade(g.quality)}>
          <span className={s.gradeTop}>
            {g.label}
            <Kbd>{g.hotkey}</Kbd>
          </span>
          <span className={s.gradeBody}>{g.body}</span>
        </button>
      ))}
    </div>
  )
}

export function AnswerReveal({ answer, explanation }: { answer?: string | null; explanation?: string | null }) {
  return (
    <div className={s.reveal}>
      <p className={s.answerLabel}>参考答案</p>
      {answer ? (
        <p className={s.answer}>{answer}</p>
      ) : (
        <p className={s.answer} data-empty="true">
          这道题没有记录标准答案。请对照资料或笔记判断自己答得怎么样。
        </p>
      )}
      {explanation && (
        <p className={s.explain}>
          <strong>为什么</strong>
          {explanation}
        </p>
      )}
    </div>
  )
}

export const recallStyles = s
