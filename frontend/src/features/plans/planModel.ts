import { localDay } from '../../lib/dates'

/*
 * Pure helpers for the daily plan documents: checklist parsing and toggling
 * (plans are markdown, tasks are "- [ ]" lines), month grids, and a readable
 * name for each day.
 */

export interface ChecklistItem {
  line: number
  title: string
  done: boolean
}

const CHECK = /^(\s*[-*+]\s+\[)([ xX])(\]\s+)(.+)$/

export function checklistOf(content: string): ChecklistItem[] {
  const out: ChecklistItem[] = []
  content.split('\n').forEach((raw, line) => {
    const m = CHECK.exec(raw)
    if (m) out.push({ line, title: m[4].trim(), done: m[2].toLowerCase() === 'x' })
  })
  return out
}

export interface PlanStats {
  total: number
  done: number
  ratio: number
}

export function statsOf(content: string): PlanStats {
  const items = checklistOf(content)
  const done = items.filter(i => i.done).length
  return { total: items.length, done, ratio: items.length ? done / items.length : 0 }
}

/** Flip one checklist line; returns the content unchanged if the line isn't a task. */
export function toggleLine(content: string, line: number): string {
  const lines = content.split('\n')
  const m = CHECK.exec(lines[line] ?? '')
  if (!m) return content
  lines[line] = `${m[1]}${m[2].trim() ? ' ' : 'x'}${m[3]}${m[4]}`
  return lines.join('\n')
}

/** Append checklist items under the content, keeping one blank line before. */
export function appendTasks(content: string, titles: string[]): string {
  const clean = titles.map(t => t.trim()).filter(Boolean)
  if (clean.length === 0) return content
  const block = clean.map(t => `- [ ] ${t}`).join('\n')
  const base = content.trimEnd()
  return base ? `${base}\n\n${block}\n` : `${block}\n`
}

/** First meaningful line of a plan, for list previews. */
export function previewOf(content: string): string {
  for (const raw of content.split('\n')) {
    const line = raw.trim()
    if (!line || line.startsWith('#') || line === '---') continue
    const task = CHECK.exec(raw)
    return (task ? task[4] : line.replace(/^[-*+>]\s+/, '')).replace(/[*_`]/g, '').trim()
  }
  return ''
}

/* ---------------- Calendar ---------------- */

export interface MonthCell {
  day: string
  inMonth: boolean
  isToday: boolean
}

/** Six-row Monday-first month grid for a YYYY-MM month. */
export function monthGrid(month: string, today: string = localDay()): MonthCell[] {
  const [y, m] = month.split('-').map(Number)
  const first = new Date(y, m - 1, 1)
  const offset = (first.getDay() + 6) % 7
  const start = new Date(y, m - 1, 1 - offset)
  return Array.from({ length: 42 }, (_, i) => {
    const d = new Date(start.getFullYear(), start.getMonth(), start.getDate() + i)
    const day = localDay(d)
    return { day, inMonth: d.getMonth() === m - 1, isToday: day === today }
  })
}

export function shiftMonth(month: string, delta: number): string {
  const [y, m] = month.split('-').map(Number)
  const d = new Date(y, m - 1 + delta, 1)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
}

export function monthRange(month: string): { start: string; end: string } {
  const grid = monthGrid(month)
  return { start: grid[0].day, end: grid[grid.length - 1].day }
}

const WEEKDAY = ['日', '一', '二', '三', '四', '五', '六']

/** "今天 · 9月25日 周五", "明天 · …", "9月27日 周日" */
export function dayTitle(day: string, today: string = localDay()): { primary: string; secondary: string } {
  const [y, m, d] = day.split('-').map(Number)
  const date = new Date(y, m - 1, d)
  const base = `${m}月${d}日`
  const week = `周${WEEKDAY[date.getDay()]}`
  const t = Date.parse(`${today}T00:00:00`)
  const diff = Math.round((date.getTime() - t) / 86_400_000)
  const rel = diff === 0 ? '今天' : diff === 1 ? '明天' : diff === -1 ? '昨天' : null
  return rel ? { primary: rel, secondary: `${base} ${week}` } : { primary: base, secondary: `${y}年 · ${week}` }
}

export function isPlainDay(value: string | null | undefined): value is string {
  if (!value || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return false
  const [y, m, d] = value.split('-').map(Number)
  const date = new Date(y, m - 1, d)
  return date.getFullYear() === y && date.getMonth() === m - 1 && date.getDate() === d
}
