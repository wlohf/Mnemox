import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import * as RDialog from '@radix-ui/react-dialog'
import { useNavigate } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import {
  ArrowUpDown,
  CornerDownLeft,
  MessageSquarePlus,
  MessageSquareText,
  Moon,
  PanelLeft,
  PanelRight,
  Plus,
  Search,
  Settings,
  Sun,
  Timer,
} from 'lucide-react'
import { Kbd } from '../../ui'
import { useThemeStore } from '../../stores/themeStore'
import type { Conversation } from '../../services/conversationApi'
import { getConversationPath } from '../../services/conversationRoute'
import { ALL_NAV, EXTRA_DESTINATIONS } from '../nav'
import { useShell } from './shellStore'
import s from './command.module.css'

interface Cmd {
  id: string
  group: string
  label: string
  icon: ReactNode
  hint?: string
  keywords?: string
  run: () => void
}

function highlight(label: string, q: string) {
  if (!q) return label
  const i = label.toLowerCase().indexOf(q.toLowerCase())
  if (i < 0) return label
  return (
    <>
      {label.slice(0, i)}
      <mark>{label.slice(i, i + q.length)}</mark>
      {label.slice(i + q.length)}
    </>
  )
}

export function CommandPalette() {
  const open = useShell(st => st.commandOpen)
  const setOpen = useShell(st => st.setCommandOpen)
  const navigate = useNavigate()
  const qc = useQueryClient()
  const toggleTheme = useThemeStore(st => st.toggle)
  const dark = useThemeStore(st => st.resolvedTheme === 'dark')
  const [q, setQ] = useState('')
  const [idx, setIdx] = useState(0)
  const listRef = useRef<HTMLDivElement | null>(null)

  const cmds = useMemo<Cmd[]>(() => {
    const go = (path: string) => () => navigate(path)
    const shell = useShell.getState()
    const actions: Cmd[] = [
      { id: 'a-ask', group: '操作', label: '问教练一个问题', icon: <MessageSquarePlus />, keywords: 'chat ask 对话 提问', run: go('/') },
      { id: 'a-focus', group: '操作', label: '开始 25 分钟专注', icon: <Timer />, keywords: 'pomodoro 番茄 focus', run: go('/pomodoro?quick=25') },
      { id: 'a-note', group: '操作', label: '新建笔记', icon: <Plus />, keywords: 'note 笔记', run: go('/notes?new=1') },
      { id: 'a-theme', group: '操作', label: dark ? '切换到浅色' : '切换到深色', icon: dark ? <Sun /> : <Moon />, keywords: 'theme 主题 dark light', run: toggleTheme },
      { id: 'a-side', group: '操作', label: '展开 / 收起侧栏', icon: <PanelLeft />, hint: 'Ctrl \\', keywords: 'sidebar', run: shell.toggleSidebar },
      { id: 'a-aside', group: '操作', label: '打开 / 关闭上下文面板', icon: <PanelRight />, hint: 'Ctrl .', keywords: 'evidence 证据 panel', run: shell.toggleAside },
      { id: 'a-settings', group: '操作', label: '打开设置', icon: <Settings />, hint: 'Ctrl ,', keywords: 'settings 设置 ai 模型', run: () => shell.openSettings('appearance') },
      { id: 'a-ai', group: '操作', label: 'AI 模型与联网搜索', icon: <Settings />, keywords: 'provider model 模型 api key 搜索', run: () => shell.openSettings('ai') },
      { id: 'a-prompts', group: '操作', label: '编辑提示词', icon: <Settings />, keywords: 'prompt 提示词 模板', run: () => shell.openSettings('prompts') },
    ]
    const pages: Cmd[] = [...ALL_NAV.map(n => ({ path: n.path, label: n.label, icon: n.icon, keywords: '' })), ...EXTRA_DESTINATIONS].map(
      d => ({ id: `p-${d.path}`, group: '前往', label: d.label, icon: d.icon, keywords: d.keywords, run: go(d.path) }),
    )
    const convs = (qc.getQueryData<Conversation[]>(['conversations', '', 'all']) ?? []).slice(0, 8).map(c => ({
      id: `c-${c.id}`,
      group: '最近对话',
      label: c.title || '未命名对话',
      icon: <MessageSquareText />,
      hint: c.updated_at?.slice(5, 10).replace('-', '/'),
      run: go(getConversationPath(c.id)),
    }))
    return [...actions, ...pages, ...convs]
  }, [navigate, qc, toggleTheme, dark, open])

  const filtered = useMemo(() => {
    const k = q.trim().toLowerCase()
    if (!k) return cmds
    return cmds.filter(c => c.label.toLowerCase().includes(k) || c.group.includes(k) || (c.keywords ?? '').toLowerCase().includes(k))
  }, [cmds, q])

  useEffect(() => setIdx(0), [q, open])
  useEffect(() => {
    if (!open) setQ('')
  }, [open])
  useEffect(() => {
    listRef.current?.querySelector('[data-active="true"]')?.scrollIntoView({ block: 'nearest' })
  }, [idx])

  const run = (c?: Cmd) => {
    if (!c) {
      const text = q.trim()
      if (text) navigate(`/?ask=${encodeURIComponent(text)}`)
      setOpen(false)
      return
    }
    setOpen(false)
    // Let the dialog release focus before navigating / opening another layer.
    requestAnimationFrame(() => c.run())
  }

  let lastGroup = ''
  return (
    <RDialog.Root open={open} onOpenChange={setOpen}>
      <RDialog.Portal>
        <RDialog.Overlay className={s.overlay} />
        <RDialog.Content
          className={s.palette}
          aria-describedby={undefined}
          onKeyDown={e => {
            if (e.key === 'ArrowDown') {
              e.preventDefault()
              setIdx(i => Math.min(i + 1, filtered.length - 1))
            } else if (e.key === 'ArrowUp') {
              e.preventDefault()
              setIdx(i => Math.max(i - 1, 0))
            } else if (e.key === 'Enter' && !e.nativeEvent.isComposing) {
              e.preventDefault()
              run(filtered[idx])
            }
          }}
        >
          <RDialog.Title className="mx-visually-hidden">命令面板</RDialog.Title>
          <div className={s.inputRow}>
            <Search aria-hidden />
            <input
              autoFocus
              className={s.input}
              placeholder="搜索页面、对话，或输入一个问题…"
              value={q}
              onChange={e => setQ(e.target.value)}
              role="combobox"
              aria-expanded
              aria-controls="mx-command-list"
              aria-activedescendant={filtered[idx] ? `cmd-${filtered[idx].id}` : undefined}
            />
            <Kbd>Esc</Kbd>
          </div>
          <div className={s.list} role="listbox" id="mx-command-list" ref={listRef}>
            {filtered.length === 0 && (
              <div className={s.empty}>
                没有匹配的页面或操作。按 <strong>Enter</strong> 把「{q}」发给教练。
              </div>
            )}
            {filtered.map((c, i) => {
              const header = c.group !== lastGroup ? (lastGroup = c.group) : null
              return (
                <div key={c.id}>
                  {header && <div className={s.group}>{header}</div>}
                  <button
                    id={`cmd-${c.id}`}
                    type="button"
                    role="option"
                    aria-selected={i === idx}
                    className={s.item}
                    data-active={i === idx || undefined}
                    onMouseMove={() => setIdx(i)}
                    onClick={() => run(c)}
                  >
                    {c.icon}
                    <span className={s.itemLabel}>{highlight(c.label, q.trim())}</span>
                    {c.hint && <span className={s.hint}>{c.hint}</span>}
                  </button>
                </div>
              )
            })}
          </div>
          <div className={s.foot}>
            <span>
              <ArrowUpDown aria-hidden />
              选择
            </span>
            <span>
              <CornerDownLeft aria-hidden />
              打开
            </span>
            <span style={{ marginLeft: 'auto' }}>Ctrl K 随时呼出</span>
          </div>
        </RDialog.Content>
      </RDialog.Portal>
    </RDialog.Root>
  )
}
