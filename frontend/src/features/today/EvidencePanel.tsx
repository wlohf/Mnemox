import { useEffect, useRef, useState, type CSSProperties } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { ExternalLink, ShieldCheck, X } from 'lucide-react'
import { Button, Empty, Highlight, IconButton, Tabs, toast } from '../../ui'
import {
  confirmAgentMemoryCandidate,
  ignoreAgentMemoryCandidate,
  type AgentMemoryCandidate,
} from '../../services/agentApi'
import { qk } from '../../app/queryClient'
import { useShell } from '../../app/shell/shellStore'
import { SOURCE_KIND, type EvidenceSource } from './evidence'
import s from './evidence.module.css'

function Excerpt({ src, lit }: { src: EvidenceSource; lit: boolean }) {
  if (!src.excerpt) return null
  if (!src.highlight || !src.excerpt.includes(src.highlight)) return <p className={s.srcExcerpt}>{src.excerpt}</p>
  const [a, ...rest] = src.excerpt.split(src.highlight)
  return (
    <p className={s.srcExcerpt}>
      {a}
      <Highlight lit={lit}>{src.highlight}</Highlight>
      {rest.join(src.highlight)}
    </p>
  )
}

export interface CoreMemoryLine {
  text: string
  meta: string
}

export function EvidencePanel({
  sources,
  active,
  onActive,
  memories,
  candidates,
  intro,
}: {
  sources: EvidenceSource[]
  active: number | null
  onActive: (n: number) => void
  memories: CoreMemoryLine[]
  candidates: AgentMemoryCandidate[]
  intro?: string
}) {
  const navigate = useNavigate()
  const qc = useQueryClient()
  const setAsideOpen = useShell(st => st.setAsideOpen)
  const [tab, setTab] = useState<'sources' | 'memory'>('sources')
  const refs = useRef<Record<number, HTMLElement | null>>({})
  const [busy, setBusy] = useState<number | null>(null)

  useEffect(() => {
    if (active == null) return
    setTab('sources')
    requestAnimationFrame(() => refs.current[active]?.scrollIntoView({ block: 'nearest', behavior: 'smooth' }))
  }, [active])

  const decide = async (c: AgentMemoryCandidate, action: 'confirm' | 'ignore') => {
    setBusy(c.id)
    const res = action === 'confirm' ? await confirmAgentMemoryCandidate(c.id) : await ignoreAgentMemoryCandidate(c.id, { reason: 'ignored' })
    setBusy(null)
    if (!res) {
      toast.error('操作没有成功，请稍后重试')
      return
    }
    toast.success(action === 'confirm' ? '已确认，教练之后会参考这条记忆' : '已忽略这条候选记忆')
    void qc.invalidateQueries({ queryKey: qk.memoryCandidates })
    void qc.invalidateQueries({ queryKey: qk.coreProfile })
  }

  const pending = candidates.filter(c => (c.review_status ?? c.status) === 'staged')

  return (
    <>
      <div className={s.head}>
        <span className={s.headTitle}>证据</span>
        <span className={s.headCount}>{sources.length}</span>
        <div className={s.headEnd}>
          <IconButton label="关闭证据面板" kbd={['Ctrl', '.']} size="sm" onClick={() => setAsideOpen(false)}>
            <X />
          </IconButton>
        </div>
      </div>
      <div className={s.tabs}>
        <Tabs
          variant="pill"
          value={tab}
          onValueChange={setTab}
          items={[
            { value: 'sources', label: '建议来源' },
            { value: 'memory', label: '正在使用的记忆', count: pending.length || undefined },
          ]}
        />
      </div>

      {tab === 'sources' ? (
        <>
          <p className={s.intro}>{intro ?? `今天的建议引用了以下 ${sources.length} 条你自己的学习记录。点击编号可以定位原文。`}</p>
          <div className={s.list}>
            {sources.length === 0 && (
              <Empty
                title="还没有可引用的记录"
                body="完成一次复习、记录一道错题或写一条笔记后，建议会开始附上来源。"
              />
            )}
            {sources.map((src, i) => (
              <article
                key={src.key}
                ref={el => {
                  refs.current[src.n] = el
                }}
                className={s.src}
                data-active={active === src.n || undefined}
                style={{ '--i': i } as CSSProperties}
                onClick={() => onActive(src.n)}
                tabIndex={0}
                onKeyDown={e => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault()
                    onActive(src.n)
                  }
                }}
                aria-label={`来源 ${src.n}：${src.title}`}
              >
                <div className={s.srcTop}>
                  <span className={s.srcNum}>{src.n}</span>
                  <span className={s.srcKind}>
                    {SOURCE_KIND[src.kind].icon}
                    {SOURCE_KIND[src.kind].label}
                  </span>
                  {src.route && (
                    <span className={s.srcOpen}>
                      <IconButton
                        label="打开原文"
                        size="sm"
                        onClick={e => {
                          e.stopPropagation()
                          navigate(src.route!)
                        }}
                      >
                        <ExternalLink />
                      </IconButton>
                    </span>
                  )}
                </div>
                <h4 className={s.srcTitle}>{src.title}</h4>
                {src.meta && <p className={s.srcMeta}>{src.meta}</p>}
                <Excerpt src={src} lit={active === src.n} />
              </article>
            ))}
          </div>
        </>
      ) : (
        <>
          <p className={s.intro}>教练在今天的建议里参考了这些长期记忆。候选记忆需要你确认后才会生效。</p>
          <div className={s.list}>
            {pending.map((c, i) => (
              <div key={c.id} className={s.memo} data-pending style={{ '--i': i } as CSSProperties}>
                <p className={s.memoText}>{c.memory_value}</p>
                <div className={s.memoMeta}>
                  <span style={{ color: 'var(--mx-ink-text)' }}>待确认的候选记忆</span>
                  {typeof c.confidence === 'number' && <span>· 置信度 {Math.round(c.confidence * 100)}%</span>}
                </div>
                <div className={s.memoActions}>
                  <Button size="sm" variant="primary" loading={busy === c.id} onClick={() => void decide(c, 'confirm')}>
                    确认
                  </Button>
                  <Button size="sm" variant="ghost" disabled={busy === c.id} onClick={() => void decide(c, 'ignore')}>
                    忽略
                  </Button>
                </div>
              </div>
            ))}
            {memories.map((m, i) => (
              <div key={m.text} className={s.memo} style={{ '--i': i + pending.length } as CSSProperties}>
                <p className={s.memoText}>{m.text}</p>
                <div className={s.memoMeta}>
                  <i />
                  <span>{m.meta}</span>
                </div>
              </div>
            ))}
            {pending.length === 0 && memories.length === 0 && (
              <Empty title="还没有长期记忆" body="和教练多聊几次、完成几次专注后，它会提炼出你的学习偏好。" />
            )}
            <Button variant="ghost" size="sm" onClick={() => navigate('/memory')} style={{ alignSelf: 'flex-start' }}>
              管理全部记忆
            </Button>
          </div>
        </>
      )}

      <div className={s.foot}>
        <ShieldCheck aria-hidden />
        所有来源都保存在你的账号里，教练不会在你确认之前写入任何数据。
      </div>
    </>
  )
}
