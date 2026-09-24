import {
  BookOpenCheck, CalendarRange, ChartNoAxesColumn, CircleX, FileText, Grid3x3, Layers,
  MessageSquareText, PanelLeft, Search, Settings, Sunrise, Target, Timer, Brain, Command,
} from 'lucide-react'
import type { ReactNode } from 'react'
import { IconButton, Kbd, ProgressRing } from '../../ui'
import { recentChats, userName } from '../data'
import s from './shell.module.css'

interface NavEntry { key: string; label: string; icon: ReactNode; badge?: string; tone?: 'evidence' }

const PRIMARY: NavEntry[] = [
  { key: 'today', label: '今天', icon: <Sunrise /> },
  { key: 'coach', label: '教练对话', icon: <MessageSquareText /> },
]

const GROUPS: Array<{ label: string; items: NavEntry[] }> = [
  {
    label: '学习',
    items: [
      { key: 'review', label: '复习', icon: <BookOpenCheck />, badge: '12', tone: 'evidence' },
      { key: 'notes', label: '笔记', icon: <FileText /> },
      { key: 'wrong', label: '错题本', icon: <CircleX />, badge: '2' },
      { key: 'anki', label: '卡片库', icon: <Layers /> },
    ],
  },
  {
    label: '规划',
    items: [
      { key: 'plans', label: '学习计划', icon: <CalendarRange /> },
      { key: 'goals', label: '目标', icon: <Target /> },
      { key: 'focus', label: '专注', icon: <Timer /> },
    ],
  },
  {
    label: '洞察',
    items: [
      { key: 'mastery', label: '掌握度', icon: <Grid3x3 /> },
      { key: 'report', label: '学习报告', icon: <ChartNoAxesColumn /> },
      { key: 'memory', label: '长期记忆', icon: <Brain /> },
    ],
  },
]

export function BrandMark() {
  // Two overlapping page arcs: a book spine that also reads as an "M".
  return (
    <svg viewBox="0 0 16 16" fill="none" aria-hidden>
      <path d="M2.5 12.5V5.2c0-.8.9-1.3 1.6-.9L8 6.6l3.9-2.3c.7-.4 1.6.1 1.6.9v7.3" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M8 6.6v6.2" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" />
    </svg>
  )
}

export function Sidebar({ current, onNavigate, onToggle, onOpenCommand }: {
  current: string
  onNavigate: (key: string) => void
  onToggle: () => void
  onOpenCommand: () => void
}) {
  const item = (n: NavEntry) => (
    <button
      key={n.key}
      type="button"
      className={s.navItem}
      aria-current={current === n.key ? 'page' : undefined}
      onClick={() => onNavigate(n.key)}
      title={n.label}
    >
      {n.icon}
      <span className={s.navText}>{n.label}</span>
      {n.badge && <span className={s.navBadge} data-tone={n.tone}>{n.badge}</span>}
    </button>
  )

  return (
    <aside className={s.sidebar} aria-label="主导航">
      <div className={s.brandRow}>
        <div className={s.brand}>
          <span className={s.brandMark}><BrandMark /></span>
          <span className={s.brandName}>Mnemox</span>
        </div>
        <IconButton label="收起侧栏" kbd={['⌘', '\\']} size="sm" onClick={onToggle} className={s.desktopOnly}>
          <PanelLeft />
        </IconButton>
      </div>

      <button type="button" className={s.search} onClick={onOpenCommand}>
        <Search />
        <span className={s.grow}>搜索或跳转…</span>
        <span className={s.keys}><Kbd><Command size={10} /></Kbd><Kbd>K</Kbd></span>
      </button>

      <nav className={s.navScroll}>
        <div className={s.navGroup}>
          {PRIMARY.map(item)}
          <div className={s.recent}>
            {recentChats.map(t => <button key={t} type="button" className={s.recentItem}>{t}</button>)}
          </div>
        </div>
        {GROUPS.map(g => (
          <div key={g.label} className={s.navGroup}>
            <div className={s.navLabel}>{g.label}</div>
            {g.items.map(item)}
          </div>
        ))}
      </nav>

      <button type="button" className={s.focusDock} title="专注计时">
        <ProgressRing value={0.38} size={30} stroke={3} color="var(--mx-evidence)">
          <span className={s.focusPulse} />
        </ProgressRing>
        <span className={s.focusMeta}>
          <span className={`${s.focusTime} mx-num`}>15:24</span>
          <span className={s.focusLabel}>专注中 · 错题重做</span>
        </span>
      </button>

      <div className={s.account}>
        <span className={s.avatar}>{userName.slice(0, 1)}</span>
        <div className={s.accountText}>
          <div className={s.accountName}>{userName}</div>
          <div className={s.accountSync}><i />本地已同步</div>
        </div>
        <span className={s.accountTools}>
          <IconButton label="设置" kbd={['⌘', ',']} size="sm"><Settings /></IconButton>
        </span>
      </div>
    </aside>
  )
}
