import { useEffect, useRef, useState } from 'react'
import { BookOpenCheck, Brain, CircleX, ExternalLink, FileText, Library, ShieldCheck, X } from 'lucide-react'
import { IconButton } from '../../ui'
import { sources, type EvidenceSource, type SourceKind } from '../data'
import s from './panels.module.css'

const KIND: Record<SourceKind, { label: string; icon: JSX.Element }> = {
  wrong: { label: '错题', icon: <CircleX /> },
  review: { label: '复习', icon: <BookOpenCheck /> },
  note: { label: '笔记', icon: <FileText /> },
  memory: { label: '记忆', icon: <Brain /> },
  material: { label: '资料', icon: <Library /> },
}

function Excerpt({ src }: { src: EvidenceSource }) {
  if (!src.highlight || !src.excerpt.includes(src.highlight)) return <p className={s.srcExcerpt}>{src.excerpt}</p>
  const [a, b] = src.excerpt.split(src.highlight)
  return <p className={s.srcExcerpt}>{a}<mark>{src.highlight}</mark>{b}</p>
}

const MEMORIES = [
  { text: '目标：12 月考研数学一，线性代数是当前短板。', meta: '你设定 · 8月30日' },
  { text: '偏好先看例题再看定理，讲解要分步。', meta: '待确认草案', pending: true },
  { text: '晚上 20:00–22:00 推导题完成率最高。', meta: '由番茄记录推断 · 已确认' },
]

export function EvidencePanel({ active, onActive, onClose }: {
  active: number | null
  onActive: (id: number) => void
  onClose: () => void
}) {
  const [tab, setTab] = useState<'sources' | 'memory'>('sources')
  const refs = useRef<Record<number, HTMLElement | null>>({})

  useEffect(() => {
    if (active == null) return
    setTab('sources')
    requestAnimationFrame(() => refs.current[active]?.scrollIntoView({ block: 'nearest', behavior: 'smooth' }))
  }, [active])

  return (
    <>
      <div className={s.head}>
        <span className={s.headTitle}>证据</span>
        <span className={`${s.headCount} mx-num`}>{sources.length}</span>
        <div className={s.headEnd}>
          <IconButton label="关闭证据面板" kbd={['⌘', '.']} size="sm" onClick={onClose}><X /></IconButton>
        </div>
      </div>
      <div className={s.tabs} role="tablist">
        <button role="tab" aria-selected={tab === 'sources'} className={s.tab} onClick={() => setTab('sources')}>建议来源</button>
        <button role="tab" aria-selected={tab === 'memory'} className={s.tab} onClick={() => setTab('memory')}>正在使用的记忆</button>
      </div>

      {tab === 'sources' ? (
        <>
          <p className={s.intro}>「下一步」建议引用了以下 4 条你自己的学习记录。点击编号可定位原文。</p>
          <div className={s.list}>
            {sources.map((src, i) => (
              <article
                key={src.id}
                ref={el => { refs.current[src.id] = el }}
                className={s.src}
                data-active={active === src.id || undefined}
                style={{ '--i': i } as React.CSSProperties}
                onClick={() => onActive(src.id)}
              >
                <div className={s.srcTop}>
                  <span className={s.srcNum}>{src.id}</span>
                  <span className={s.srcKind}>{KIND[src.kind].icon}{KIND[src.kind].label}</span>
                  <span className={s.srcOpen}><IconButton label="打开原文" size="sm"><ExternalLink /></IconButton></span>
                </div>
                <h4 className={s.srcTitle}>{src.title}</h4>
                <p className={s.srcMeta}>{src.meta}</p>
                <Excerpt src={src} />
              </article>
            ))}
          </div>
        </>
      ) : (
        <>
          <p className={s.intro}>教练在本次建议里参考了这些长期记忆。你可以随时修改或删除。</p>
          <div className={s.list}>
            {MEMORIES.map((m, i) => (
              <div key={m.text} className={s.memo} style={{ '--i': i } as React.CSSProperties}>
                <p className={s.memoText}>{m.text}</p>
                <div className={s.memoMeta}>
                  {!m.pending && <i />}
                  <span style={m.pending ? { color: 'var(--mx-ink-text)' } : undefined}>{m.meta}</span>
                </div>
              </div>
            ))}
          </div>
        </>
      )}

      <div className={s.foot}><ShieldCheck />所有来源都保存在本机，教练不会在未确认时写入任何数据。</div>
    </>
  )
}
