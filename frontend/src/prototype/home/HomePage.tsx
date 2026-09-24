import { useState, type CSSProperties } from 'react'
import {
  ArrowRight, ArrowUp, AtSign, BookOpenCheck, Check, ChevronRight, CircleX, Clock3, Compass,
  Paperclip, Pencil, Play, Sparkle, Target, Timer, X, Mic,
} from 'lucide-react'
import { Button, Cite, CountUp, IconButton, ProgressRing, cx } from '../../ui'
import { drafts, goal, mastery, nextAction, queue, stats, userName, type QueueKind } from '../data'
import s from './home.module.css'

const QUEUE_ICON: Record<QueueKind, JSX.Element> = {
  focus: <Timer />,
  task: <Target />,
  wrong: <CircleX />,
  review: <BookOpenCheck />,
}
const QUEUE_LABEL: Record<QueueKind, string> = { focus: '专注', task: '任务', wrong: '错题', review: '复习' }

const rise = (i: number) => ({ '--i': i } as CSSProperties)

function Greeting() {
  const now = new Date()
  const week = '日一二三四五六'[now.getDay()]
  const h = now.getHours()
  const hello = h < 5 ? '夜深了' : h < 11 ? '早上好' : h < 14 ? '中午好' : h < 18 ? '下午好' : '晚上好'
  return (
    <header className={cx(s.greet, s.rise)} style={rise(0)}>
      <div>
        <div className={s.date}>
          <span>{now.getMonth() + 1}月{now.getDate()}日 星期{week}</span><i />
          <span>距考试 <span className="mx-num">{goal.daysLeft}</span> 天</span>
        </div>
        <h1 className={s.hello}>{hello}，{userName}</h1>
        <p className={s.helloSub}>今天还剩 <b>3 件事</b>，大约 <b>55 分钟</b>。先做最关键的那一件。</p>
      </div>
      <button type="button" className={s.goalPill}>
        <ProgressRing value={goal.progress} size={36} stroke={3}>
          <span className={cx(s.goalPct, 'mx-num')}>{Math.round(goal.progress * 100)}</span>
        </ProgressRing>
        <span className={s.goalText}>
          <span className={s.goalTitle}>{goal.title}</span>
          <span className={s.goalMeta}>本周 <span className="mx-num">{goal.weekMinutes}</span> / {goal.weekTarget} 分钟</span>
        </span>
      </button>
    </header>
  )
}

function NextAction({ activeCite, onCite }: { activeCite: number | null; onCite: (n: number) => void }) {
  const total = nextAction.steps.reduce((a, b) => a + b.minutes, 0)
  return (
    <section className={cx(s.next, s.rise)} style={rise(1)} aria-labelledby="next-title">
      <div className={s.eyebrow}>
        <Compass />下一步
        <span className={s.eyebrowMuted}>约 <span className="mx-num">{total}</span> 分钟 · 3 步</span>
      </div>
      <h2 id="next-title" className={s.nextTitle}>{nextAction.title}</h2>

      <ol className={s.steps}>
        {nextAction.steps.map((st, i) => (
          <li key={st.label} className={s.step}>
            <span className={cx(s.stepIdx, 'mx-num')}>{i + 1}</span>
            <span className={s.stepText}>{st.label}</span>
            <span>{st.cite.map(c => <Cite key={c} n={c} active={activeCite === c} onClick={() => onCite(c)} />)}</span>
            <span className={cx(s.stepMin, 'mx-num')}>{st.minutes} min</span>
          </li>
        ))}
      </ol>

      <div className={s.reason}>
        <span className={s.reasonLabel}>为什么</span>
        <span>
          {nextAction.reason}{' '}
          {nextAction.reasonCites.map(c => <Cite key={c} n={c} active={activeCite === c} onClick={() => onCite(c)} />)}
          <span className={s.caret} aria-hidden />
        </span>
      </div>

      <div className={s.nextActions}>
        <Button variant="primary" icon={<Play />}>开始专注 45 分钟</Button>
        <Button variant="secondary" icon={<Pencil />}>调整计划</Button>
        <span className={s.spacer} />
        <Button variant="ghost" size="sm">换一个建议</Button>
      </div>
    </section>
  )
}

function Queue() {
  const nowId = queue.find(q => !q.done)?.id
  const left = queue.filter(q => !q.done).length
  return (
    <section className={s.rise} style={rise(2)}>
      <div className={s.sectionHead}>
        <h3 className={s.sectionTitle}>今日安排</h3>
        <span className={s.sectionMeta}><span className="mx-num">{queue.length - left}</span> / {queue.length} 已完成</span>
        <button type="button" className={s.sectionLink}>查看计划<ChevronRight /></button>
      </div>
      <ul className={s.queue}>
        {queue.map(q => (
          <li key={q.id} className={s.qItem} data-done={q.done || undefined} data-now={q.id === nowId || undefined} tabIndex={0}>
            <span className={cx(s.qTime, 'mx-num')}>{q.time}</span>
            <span className={s.qDot}>{q.done ? <Check /> : QUEUE_ICON[q.kind]}</span>
            <span className={s.qBody}>
              <span className={s.qTitle}>{q.title}</span>
              <span className={s.qDetail}><span className={s.qKind}>{QUEUE_LABEL[q.kind]}</span>·<span>{q.detail}</span></span>
            </span>
            <span className={s.qGo}>
              {q.id === nowId
                ? <Button size="sm" variant="secondary" iconRight={<ArrowRight />}>开始</Button>
                : !q.done && <IconButton label="开始" size="sm"><ArrowRight /></IconButton>}
            </span>
          </li>
        ))}
      </ul>
    </section>
  )
}

function Drafts({ onCite }: { onCite: (n: number) => void }) {
  const [state, setState] = useState<Record<string, 'committed' | 'discarded' | 'gone'>>({})
  const visible = drafts.filter(d => state[d.id] !== 'gone')
  const discard = (id: string) => {
    setState(p => ({ ...p, [id]: 'discarded' }))
    setTimeout(() => setState(p => ({ ...p, [id]: 'gone' })), 320)
  }
  return (
    <section className={s.rise} style={rise(3)}>
      <div className={s.sectionHead}>
        <h3 className={s.sectionTitle}>待你确认</h3>
        <span className={s.sectionMeta}>教练的建议，确认后才会写入</span>
      </div>
      <div className={s.drafts}>
        {visible.length === 0 && <p className={s.sectionMeta}>都处理完了。新的建议会出现在这里。</p>}
        {visible.map(d => {
          const st = state[d.id]
          return (
            <article key={d.id} className={s.draft} data-state={st}>
              <div className={s.draftTop}>
                <span className={s.draftKind}>{st === 'committed' ? `已写入${d.kind}` : `${d.kind}草案`}</span>
                <span className={s.draftFrom}>来自今天的分析</span>
                {d.cite.length > 0 && <span style={{ marginLeft: 'auto' }}>{d.cite.map(c => <Cite key={c} n={c} onClick={() => onCite(c)} />)}</span>}
              </div>
              <h4 className={s.draftTitle}>{d.title}</h4>
              <p className={s.draftBody}>{d.body}</p>
              <div className={s.draftActions}>
                {st === 'committed' ? (
                  <>
                    <span className={s.stamp}><Check />已确认</span>
                    <span className={s.spacer} />
                    <Button size="sm" variant="ghost" onClick={() => setState(p => { const n = { ...p }; delete n[d.id]; return n })}>撤销</Button>
                  </>
                ) : (
                  <>
                    <Button size="sm" variant="primary" icon={<Check />} onClick={() => setState(p => ({ ...p, [d.id]: 'committed' }))}>确认</Button>
                    <Button size="sm" variant="ghost" icon={<Pencil />}>修改</Button>
                    <span className={s.spacer} />
                    <IconButton label="忽略" size="sm" onClick={() => discard(d.id)}><X /></IconButton>
                  </>
                )}
              </div>
            </article>
          )
        })}
      </div>
    </section>
  )
}

function Stats() {
  return (
    <section className={s.rise} style={rise(2)}>
      <div className={s.sectionHead}>
        <h3 className={s.sectionTitle}>今天的节奏</h3>
      </div>
      <div className={s.stats}>
        {stats.map(st => (
          <div key={st.key} className={s.stat}>
            <div className={s.statLabel}>{st.label}</div>
            <div className={s.statValue}><span className={s.statNum}><CountUp value={st.value} /></span><span className={s.statUnit}>{st.unit}</span></div>
            <div className={s.statDelta}>{st.delta}</div>
          </div>
        ))}
      </div>
    </section>
  )
}

function Mastery() {
  let d = 0
  return (
    <section className={s.rise} style={rise(3)}>
      <div className={s.sectionHead}>
        <h3 className={s.sectionTitle}>掌握度 · 线性代数</h3>
        <button type="button" className={s.sectionLink}>全部<ChevronRight /></button>
      </div>
      <div className={s.mastery}>
        {mastery.map(m => (
          <div key={m.chapter} className={s.mRow} data-focus={m.chapter === '特征值' || undefined}>
            <span className={s.mName}>{m.chapter}</span>
            <span className={s.mCells}>
              {m.topics.map((l, i) => (
                <span key={i} className={s.mCell} data-l={l} style={{ '--d': d++ } as CSSProperties} title={`掌握度 ${l}/5`} />
              ))}
            </span>
          </div>
        ))}
        <div className={s.legend}>
          未学
          {[0, 1, 2, 3, 4, 5].map(l => <span key={l} className={s.mCell} data-l={l} style={{ animation: 'none' }} />)}
          牢固
        </div>
      </div>
    </section>
  )
}

export function Composer() {
  const [text, setText] = useState('')
  const [ctx, setCtx] = useState(true)
  return (
    <div className={s.composerDock}>
      <div className={s.composer}>
        {ctx && (
          <div className={s.composerCtx}>
            <span className={s.ctxChip}><AtSign />相似对角化 · 错题 2<button type="button" aria-label="移除上下文" onClick={() => setCtx(false)}><X /></button></span>
            <span className={s.ctxHint}>已自动带上当前任务</span>
          </div>
        )}
        <textarea
          className={s.textarea}
          rows={1}
          placeholder="问教练：为什么重根时不一定能对角化？"
          value={text}
          onChange={e => setText(e.target.value)}
        />
        <div className={s.composerBar}>
          <IconButton label="附件" size="sm"><Paperclip /></IconButton>
          <IconButton label="语音" size="sm"><Mic /></IconButton>
          <button type="button" className={s.mode}><Sparkle />教练模式</button>
          <span className={s.spacer} />
          <button type="button" className={s.mode}><Clock3 />先想一想</button>
          <button type="button" className={s.send} disabled={!text.trim()} aria-label="发送"><ArrowUp /></button>
        </div>
      </div>
      <div className={s.composerFoot}>回答会标注来源；涉及写入的操作会先生成草案，由你确认。</div>
    </div>
  )
}

export function HomePage({ activeCite, onCite }: { activeCite: number | null; onCite: (n: number) => void }) {
  return (
    <div className={s.page}>
      <Greeting />
      <NextAction activeCite={activeCite} onCite={onCite} />
      <div className={s.grid}>
        <div className={s.col}>
          <Queue />
          <Drafts onCite={onCite} />
        </div>
        <div className={s.col}>
          <Stats />
          <Mastery />
        </div>
      </div>
    </div>
  )
}
