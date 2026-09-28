import type { EDAReport } from '../../services/analyticsApi'
import type { UserProfile } from '../../services/profileApi'

/*
 * View model for 学习报告. Everything the charts need is derived here so the
 * components only draw. Units: minutes for time, 0–100 for rates.
 */

export type Period = 7 | 30 | 90

/** "25 分钟" below an hour, "1.6 小时" from an hour up. */
export function formatMinutes(min: number | null | undefined): string {
  const m = Math.max(0, Number(min ?? 0))
  if (m < 60) return `${Math.round(m)} 分钟`
  const h = m / 60
  return `${h >= 10 ? Math.round(h) : Number(h.toFixed(1))} 小时`
}

/** Clean axis ticks from 0 to at least `max` (0 / 10 / 20 / 30 …). */
export function niceTicks(max: number, count = 4): number[] {
  const top = Math.max(1, max)
  const raw = top / count
  const mag = 10 ** Math.floor(Math.log10(raw))
  const step = [1, 2, 2.5, 5, 10].map(f => f * mag).find(s => s >= raw) ?? 10 * mag
  const ticks: number[] = []
  for (let v = 0; v < top + step * 0.999; v += step) ticks.push(Number(v.toFixed(6)))
  return ticks
}

/** Which day indexes get an x-axis label: sparse, always including the last. */
export function labelledDays(n: number): Set<number> {
  const every = n <= 10 ? 1 : n <= 35 ? 7 : 14
  const out = new Set<number>()
  for (let i = n - 1; i >= 0; i -= every) out.add(i)
  return out
}

/** "2026-09-25" → "9/25" */
export function shortMD(iso: string): string {
  const [, m, d] = iso.split('-').map(Number)
  return `${m}/${d}`
}

/* ---------------- Session outcomes ---------------- */

export type OutcomeKey = 'completed' | 'early_done' | 'interrupted' | 'distracted' | 'other'

export interface Outcome {
  key: OutcomeKey
  label: string
  count: number
}

/**
 * Split all focus sessions into outcomes. The backend reports completion as a
 * rate and stop reasons as counts (its "early_done" means finished early, not
 * completed), so full completions are derived from the rate.
 */
export function outcomesOf(summary: Pick<EDAReport['summary'], 'pomodoro_count' | 'completion_rate' | 'stop_reason_counts'>): Outcome[] {
  const total = Math.max(0, Math.round(summary.pomodoro_count ?? 0))
  const reasons = summary.stop_reason_counts ?? {}
  const completed = Math.min(total, Math.round((total * (summary.completion_rate ?? 0)) / 100))
  const early = Math.max(0, Math.round(reasons.early_done ?? 0))
  const interrupted = Math.max(0, Math.round(reasons.interrupted ?? 0))
  const distracted = Math.max(0, Math.round(reasons.distracted ?? 0))
  const other = Math.max(0, total - completed - early - interrupted - distracted)
  return [
    { key: 'completed' as const, label: '完整完成', count: completed },
    { key: 'early_done' as const, label: '提前结束', count: early },
    { key: 'interrupted' as const, label: '临时中断', count: interrupted },
    { key: 'distracted' as const, label: '走神停下', count: distracted },
    { key: 'other' as const, label: '未记录原因', count: other },
  ].filter(o => o.count > 0)
}

/* ---------------- Time of day ---------------- */

/** Hours covered by a window like "20:00-21:00" or "23:00-01:00" (end exclusive). */
export function windowHours(window: string | null | undefined): Set<number> {
  const m = /^(\d{1,2}):\d{2}\s*[-–~]\s*(\d{1,2}):\d{2}$/.exec((window ?? '').trim())
  const out = new Set<number>()
  if (!m) return out
  const start = Number(m[1]) % 24
  const end = Number(m[2]) % 24
  let h = start
  for (let guard = 0; guard < 24; guard++) {
    out.add(h)
    h = (h + 1) % 24
    if (h === end) break
  }
  return out
}

/** Five sequential steps (1–5) by share of the maximum; 0 means none. */
export function heatLevel(value: number, max: number): 0 | 1 | 2 | 3 | 4 | 5 {
  if (!(value > 0) || !(max > 0)) return 0
  const r = value / max
  if (r > 0.8) return 5
  if (r > 0.6) return 4
  if (r > 0.4) return 3
  if (r > 0.2) return 2
  return 1
}

export interface HeatGrid {
  weekdays: string[]
  /** [weekday][hour] minutes */
  cells: number[][]
  hourTotals: number[]
  dayTotals: number[]
  max: number
}

export function heatGrid(report: Pick<EDAReport, 'charts'>): HeatGrid {
  const hm = report.charts?.hour_week_heatmap
  const weekdays = hm?.weekdays?.length === 7 ? hm.weekdays : ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
  const cells = Array.from({ length: 7 }, () => Array.from({ length: 24 }, () => 0))
  for (const [hour, day, minutes] of hm?.points ?? []) {
    if (day >= 0 && day < 7 && hour >= 0 && hour < 24) cells[day][hour] += Number(minutes) || 0
  }
  const hourTotals = Array.from({ length: 24 }, (_, h) => cells.reduce((s, row) => s + row[h], 0))
  const dayTotals = cells.map(row => row.reduce((s, v) => s + v, 0))
  const max = Math.max(0, ...cells.flat())
  return { weekdays, cells, hourTotals, dayTotals, max }
}

/* ---------------- Captions (computed, not canned) ---------------- */

export function trendCaption(report: Pick<EDAReport, 'daily_points' | 'summary' | 'period_days'>): string {
  const pts = report.daily_points ?? []
  const total = report.summary?.total_minutes ?? 0
  const active = pts.filter(p => (p.study_minutes ?? 0) > 0).length
  if (active === 0) return `近 ${report.period_days} 天还没有学习记录。`
  const best = pts.reduce((a, b) => ((b.study_minutes ?? 0) > (a.study_minutes ?? 0) ? b : a))
  return `近 ${report.period_days} 天共学习 ${formatMinutes(total)}，其中 ${active} 天有记录；最长的一天是 ${shortMD(best.date)}，${formatMinutes(best.study_minutes)}。`
}

export function timeCaption(grid: HeatGrid, bestWindow?: string | null): string {
  const total = grid.hourTotals.reduce((a, b) => a + b, 0)
  if (total === 0) return '还没有足够的专注记录来判断你的高效时段。'
  const peakDay = grid.dayTotals.indexOf(Math.max(...grid.dayTotals))
  const parts = []
  if (bestWindow) parts.push(`完成率最高的时段是 ${bestWindow}`)
  parts.push(`${grid.weekdays[peakDay]}学得最多`)
  return `${parts.join('，')}。`
}

/* ---------------- Risk (daily intervention) ---------------- */

export const RISK_META: Record<string, { label: string; tone: 'success' | 'warning' | 'danger' }> = {
  low: { label: '节奏正常', tone: 'success' },
  medium: { label: '需要留意', tone: 'warning' },
  high: { label: '今天有点危险', tone: 'danger' },
}

/* ---------------- Learner profile (merged from 学习画像) ---------------- */

export interface AbilityRow {
  key: 'focus' | 'consistency'
  label: string
  /** 0–100 */
  value: number
  foot: string
}

function score(v: unknown): number {
  const n = Number(v)
  if (!Number.isFinite(n)) return 0
  return Math.round(Math.min(100, Math.max(0, n)))
}

/**
 * The abilities the backend actually measures, already on a 0–100 scale.
 * 自控力 currently mirrors 专注度 and 计划执行 is a fixed placeholder, so
 * neither is drawn as if it were data.
 */
export function abilityRows(p: Pick<UserProfile, 'focus_score' | 'consistency_score' | 'streak_days'>): AbilityRow[] {
  const streak = Math.max(0, Math.round(Number(p.streak_days) || 0))
  return [
    { key: 'focus', label: '专注度', value: score(p.focus_score), foot: '专注完整完成的比例，按全部记录计算' },
    {
      key: 'consistency',
      label: '坚持度',
      value: score(p.consistency_score),
      foot: streak > 0 ? `已连续学习 ${streak} 天，满 30 天记满分` : '按连续学习的天数计算，满 30 天记满分',
    },
  ]
}

/** Weak knowledge points in the backend's order, trimmed, unique, capped. */
export function weakPointsOf(raw: unknown, max = 10): string[] {
  if (!Array.isArray(raw)) return []
  const out: string[] = []
  for (const item of raw) {
    let name: unknown = item
    if (item && typeof item === 'object') {
      const rec = item as Record<string, unknown>
      name = rec.knowledge_point ?? rec.name
    }
    if (typeof name !== 'string') continue
    const v = name.trim()
    if (v && !out.includes(v)) out.push(v)
    if (out.length >= max) break
  }
  return out
}

/* ---------------- Deep links into the report ---------------- */

const HASH_TARGETS: Record<string, string> = {
  today: 'report-today',
  intervention: 'report-today',
  profile: 'report-profile',
}

/**
 * Section to scroll to for a URL. Keeps old links working: the daily
 * intervention (`?tab=intervention`) and the former profile page (`#profile`).
 */
export function reportTarget(search: string, hash: string): string | null {
  if (new URLSearchParams(search).get('tab') === 'intervention') return 'report-today'
  return HASH_TARGETS[hash.replace(/^#/, '')] ?? null
}
