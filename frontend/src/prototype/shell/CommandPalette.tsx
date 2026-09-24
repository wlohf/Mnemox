import { useEffect, useMemo, useState, type ReactNode } from 'react'
import * as Dialog from '@radix-ui/react-dialog'
import {
  BookOpenCheck, CalendarRange, CircleX, CornerDownLeft, FileText, MessageSquareText, Moon,
  Plus, Search, Sunrise, Timer, Grid3x3, Brain, ArrowUpDown,
} from 'lucide-react'
import { Kbd } from '../../ui'
import s from './panels.module.css'

interface Cmd { id: string; group: string; label: string; icon: ReactNode; hint?: string; run?: () => void }

export function CommandPalette({ open, onOpenChange, onToggleTheme, onNavigate }: {
  open: boolean
  onOpenChange: (v: boolean) => void
  onToggleTheme: () => void
  onNavigate: (key: string) => void
}) {
  const [q, setQ] = useState('')
  const [idx, setIdx] = useState(0)

  const cmds = useMemo<Cmd[]>(() => [
    { id: 'a1', group: '操作', label: '开始 25 分钟专注', icon: <Timer />, hint: '专注' },
    { id: 'a2', group: '操作', label: '新建笔记', icon: <Plus />, hint: '笔记' },
    { id: 'a3', group: '操作', label: '问教练一个问题', icon: <MessageSquareText />, hint: '对话' },
    { id: 'a4', group: '操作', label: '切换浅色 / 深色', icon: <Moon />, run: onToggleTheme },
    { id: 'n1', group: '跳转', label: '今天', icon: <Sunrise />, run: () => onNavigate('today') },
    { id: 'n2', group: '跳转', label: '复习 · 12 张到期', icon: <BookOpenCheck />, run: () => onNavigate('review') },
    { id: 'n3', group: '跳转', label: '错题本', icon: <CircleX />, run: () => onNavigate('wrong') },
    { id: 'n4', group: '跳转', label: '学习计划', icon: <CalendarRange />, run: () => onNavigate('plans') },
    { id: 'n5', group: '跳转', label: '掌握度', icon: <Grid3x3 />, run: () => onNavigate('mastery') },
    { id: 'n6', group: '跳转', label: '长期记忆', icon: <Brain />, run: () => onNavigate('memory') },
    { id: 's1', group: '最近内容', label: '笔记《第五章 特征值与特征向量》', icon: <FileText />, hint: '9月18日' },
    { id: 's2', group: '最近内容', label: '对话：为什么实对称矩阵一定能正交对角化', icon: <MessageSquareText />, hint: '昨天' },
  ], [onToggleTheme, onNavigate])

  const filtered = useMemo(() => {
    const k = q.trim().toLowerCase()
    return k ? cmds.filter(c => c.label.toLowerCase().includes(k) || c.group.includes(k)) : cmds
  }, [cmds, q])

  useEffect(() => { setIdx(0) }, [q, open])
  useEffect(() => { if (!open) setQ('') }, [open])

  const run = (c?: Cmd) => { if (!c) return; c.run?.(); onOpenChange(false) }

  let last = ''
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className={s.overlay} />
        <Dialog.Content
          className={s.palette}
          aria-describedby={undefined}
          onKeyDown={e => {
            if (e.key === 'ArrowDown') { e.preventDefault(); setIdx(i => Math.min(i + 1, filtered.length - 1)) }
            if (e.key === 'ArrowUp') { e.preventDefault(); setIdx(i => Math.max(i - 1, 0)) }
            if (e.key === 'Enter') { e.preventDefault(); run(filtered[idx]) }
          }}
        >
          <Dialog.Title style={{ position: 'absolute', width: 1, height: 1, overflow: 'hidden', clip: 'rect(0 0 0 0)' }}>命令面板</Dialog.Title>
          <div className={s.pInputRow}>
            <Search />
            <input
              autoFocus
              className={s.pInput}
              placeholder="搜索页面、笔记、对话，或输入一个操作…"
              value={q}
              onChange={e => setQ(e.target.value)}
            />
            <Kbd>Esc</Kbd>
          </div>
          <div className={s.pList} role="listbox">
            {filtered.length === 0 && <div className={s.pEmpty}>没有匹配的结果。按 Enter 把「{q}」发给教练。</div>}
            {filtered.map((c, i) => {
              const header = c.group !== last ? (last = c.group) : null
              return (
                <div key={c.id}>
                  {header && <div className={s.pGroup}>{header}</div>}
                  <button
                    type="button"
                    role="option"
                    aria-selected={i === idx}
                    className={s.pItem}
                    data-active={i === idx || undefined}
                    onMouseMove={() => setIdx(i)}
                    onClick={() => run(c)}
                  >
                    {c.icon}{c.label}{c.hint && <span className={s.pHint}>{c.hint}</span>}
                  </button>
                </div>
              )
            })}
          </div>
          <div className={s.pFoot}>
            <span><ArrowUpDown size={12} />选择</span>
            <span><CornerDownLeft size={12} />打开</span>
            <span style={{ marginLeft: 'auto' }}>Mnemox 命令面板</span>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
