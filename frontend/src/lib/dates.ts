const PLAIN_DAY = /^(\d{4})-(\d{2})-(\d{2})$/
const TIMEZONE_SUFFIX = /(Z|[+-]\d{2}:?\d{2})$/i
const DAY_MS = 86_400_000

export type DueTone = 'overdue' | 'today' | 'soon'

export interface DueLabel {
  text: string
  tone?: DueTone
}

function validPlainDay(value: string): boolean {
  const match = PLAIN_DAY.exec(value)
  if (!match) return false
  const year = Number(match[1])
  const month = Number(match[2])
  const day = Number(match[3])
  const date = new Date(Date.UTC(year, month - 1, day))
  return date.getUTCFullYear() === year && date.getUTCMonth() === month - 1 && date.getUTCDate() === day
}

function dayNumber(value: string): number | null {
  if (!validPlainDay(value)) return null
  const [year, month, day] = value.split('-').map(Number)
  return Date.UTC(year, month - 1, day) / DAY_MS
}

function displayDay(value: string): string {
  const [, month, day] = value.split('-').map(Number)
  return `${month}月${day}日`
}

/** Format a Date as a local calendar day without UTC date drift. */
export function localDay(date = new Date()): string {
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

/** Backend datetimes without an explicit offset are UTC. */
export function parseServerTime(value: string | null | undefined): Date | null {
  const input = value?.trim()
  if (!input) return null
  const date = new Date(TIMEZONE_SUFFIX.test(input) ? input : `${input}Z`)
  return Number.isNaN(date.getTime()) ? null : date
}

/** Convert a plain day or backend timestamp to its local calendar day. */
export function toLocalDay(value: string | null | undefined): string | null {
  const input = value?.trim()
  if (!input) return null
  if (PLAIN_DAY.test(input)) return validPlainDay(input) ? input : null
  const date = parseServerTime(input)
  return date ? localDay(date) : null
}

/** Calendar-day distance from `today` to `value`. */
export function dayDiff(value: string | null | undefined, today: string = localDay()): number | null {
  const target = toLocalDay(value)
  if (!target) return null
  const targetDay = dayNumber(target)
  const baseDay = dayNumber(today)
  return targetDay == null || baseDay == null ? null : targetDay - baseDay
}

export function shortDate(value: string | null | undefined): string {
  const day = toLocalDay(value)
  return day ? displayDay(day) : '—'
}

export function formatStamp(value: Date | string | null | undefined): string {
  const date = value instanceof Date ? value : parseServerTime(value)
  if (!date || Number.isNaN(date.getTime())) return '—'
  const hour = String(date.getHours()).padStart(2, '0')
  const minute = String(date.getMinutes()).padStart(2, '0')
  return `${date.getMonth() + 1}月${date.getDate()}日 ${hour}:${minute}`
}

export function minutesSince(value: string | null | undefined, now = Date.now()): number | null {
  const start = parseServerTime(value)
  if (!start) return null
  return Math.max(0, Math.floor((now - start.getTime()) / 60_000))
}

export function dueLabel(
  value: string | null | undefined,
  today: string = localDay(),
  completed = false,
): DueLabel | null {
  const day = toLocalDay(value)
  const diff = dayDiff(value, today)
  if (!day || diff == null) return null
  if (completed) return { text: displayDay(day) }
  if (diff < 0) return { text: `逾期 ${Math.abs(diff)} 天`, tone: 'overdue' }
  if (diff === 0) return { text: '今天', tone: 'today' }
  if (diff === 1) return { text: '明天', tone: 'soon' }
  if (diff <= 3) return { text: `${diff} 天后`, tone: 'soon' }
  return { text: displayDay(day) }
}

export function deadlineLabel(value: string | null | undefined, today: string = localDay()): DueLabel | null {
  const diff = dayDiff(value, today)
  if (diff == null) return null
  if (diff < 0) return { text: `已过期 ${Math.abs(diff)} 天`, tone: 'overdue' }
  if (diff === 0) return { text: '今天截止', tone: 'today' }
  return { text: `还剩 ${diff} 天`, tone: diff <= 3 ? 'soon' : undefined }
}
