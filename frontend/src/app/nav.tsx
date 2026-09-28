import type { ReactNode } from 'react'
import {
  BookOpenCheck,
  Brain,
  CalendarRange,
  ChartNoAxesColumn,
  CircleX,
  Compass,
  FileText,
  Grid3x3,
  Layers,
  Library,
  MessageSquareText,
  Sunrise,
  Target,
  Timer,
} from 'lucide-react'

/*
 * Navigation model. The information architecture groups the product by what
 * the learner is doing, not by feature list:
 *   今天 / 教练对话            — where the day starts
 *   学习  复习 · 错题 · 笔记 · 资料 · 卡片
 *   规划  计划 · 目标 · 专注
 *   洞察  掌握度 · 学习报告 · 长期记忆
 * Every legacy route the backend deep-links to (/review, /goals, /pomodoro …)
 * stays a first-class path.
 */

export interface NavEntry {
  key: string
  path: string
  label: string
  icon: ReactNode
  /** extra path prefixes that should mark this entry active */
  match?: string[]
  badgeKey?: 'reviewDue' | 'wrongDue' | 'memoryPending'
}

export interface NavGroup {
  key: string
  label: string
  items: NavEntry[]
}

export const PRIMARY_NAV: NavEntry[] = [
  { key: 'today', path: '/today', label: '今天', icon: <Sunrise />, match: ['/dashboard', '/agent', '/intervention'] },
  { key: 'coach', path: '/', label: '教练对话', icon: <MessageSquareText />, match: ['/conversations'] },
]

export const NAV_GROUPS: NavGroup[] = [
  {
    key: 'study',
    label: '学习',
    items: [
      { key: 'review', path: '/review', label: '复习', icon: <BookOpenCheck />, badgeKey: 'reviewDue' },
      { key: 'wrong', path: '/wrong-questions', label: '错题本', icon: <CircleX />, badgeKey: 'wrongDue' },
      { key: 'notes', path: '/notes', label: '笔记', icon: <FileText /> },
      { key: 'materials', path: '/materials', label: '资料库', icon: <Library /> },
      { key: 'anki', path: '/anki', label: '记忆卡', icon: <Layers /> },
    ],
  },
  {
    key: 'plan',
    label: '规划',
    items: [
      { key: 'plans', path: '/plans', label: '学习计划', icon: <CalendarRange /> },
      { key: 'goals', path: '/goals', label: '目标', icon: <Target /> },
      { key: 'focus', path: '/pomodoro', label: '专注', icon: <Timer /> },
    ],
  },
  {
    key: 'insight',
    label: '洞察',
    items: [
      { key: 'mastery', path: '/mastery', label: '掌握度', icon: <Grid3x3 />, match: ['/progress', '/knowledge-lab'] },
      { key: 'report', path: '/eda', label: '学习报告', icon: <ChartNoAxesColumn />, match: ['/profile'] },
      { key: 'memory', path: '/memory', label: '长期记忆', icon: <Brain />, badgeKey: 'memoryPending' },
    ],
  },
]

export const ALL_NAV: NavEntry[] = [...PRIMARY_NAV, ...NAV_GROUPS.flatMap(g => g.items)]

/** Secondary destinations reachable from pages and the command palette. */
export const EXTRA_DESTINATIONS: Array<{ path: string; label: string; icon: ReactNode; keywords?: string }> = [
  { path: '/agent', label: '教练工作台', icon: <Compass />, keywords: 'agent 自主 建议 kernel' },
  { path: '/eda#profile', label: '学习画像', icon: <ChartNoAxesColumn />, keywords: 'profile 画像 能力 薄弱' },
  { path: '/eda?tab=intervention', label: '今天的状态检查', icon: <ChartNoAxesColumn />, keywords: 'intervention 干预 提醒 风险' },
  { path: '/progress', label: '进度引擎', icon: <Grid3x3 />, keywords: 'progress 进度' },
  { path: '/knowledge-lab', label: 'Knowledge Lab', icon: <Library />, keywords: 'claim 知识 图谱 lab' },
]

function matches(pathname: string, prefix: string): boolean {
  if (prefix === '/') return pathname === '/'
  return pathname === prefix || pathname.startsWith(`${prefix}/`) || pathname.startsWith(`${prefix}?`)
}

export function isEntryActive(pathname: string, entry: NavEntry): boolean {
  if (matches(pathname, entry.path)) return true
  return (entry.match ?? []).some(p => matches(pathname, p))
}

export function findActiveEntry(pathname: string): NavEntry | undefined {
  return ALL_NAV.find(e => isEntryActive(pathname, e))
}

export function groupOf(entry: NavEntry): NavGroup | undefined {
  return NAV_GROUPS.find(g => g.items.includes(entry))
}
