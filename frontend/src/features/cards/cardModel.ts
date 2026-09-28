import type { AnkiCardItem } from '../../services/ankiApi'
import { dayDiff, localDay } from '../../lib/dates'

/*
 * View model for 记忆卡: queue composition, deck filtering, tag parsing and
 * a plain-language description of each card's schedule.
 */

export type CardState = 'new' | 'due' | 'learning' | 'mature'

/** Cards with an interval of three weeks or more count as settled. */
export const MATURE_DAYS = 21

export function tagsOf(card: Pick<AnkiCardItem, 'tags'>): string[] {
  return (card.tags ?? '')
    .split(/[,，]/)
    .map(t => t.trim())
    .filter(Boolean)
}

export function joinTags(tags: string[]): string {
  return Array.from(new Set(tags.map(t => t.trim()).filter(Boolean))).join(',')
}

export function stateOf(card: Pick<AnkiCardItem, 'last_quality' | 'due_at' | 'interval_days'>, now: number = Date.now()): CardState {
  if (card.last_quality == null) return 'new'
  const due = card.due_at ? Date.parse(card.due_at) : NaN
  if (!Number.isNaN(due) && due <= now) return 'due'
  return (card.interval_days ?? 0) >= MATURE_DAYS ? 'mature' : 'learning'
}

export const STATE_META: Record<CardState, { label: string; tone: 'ink' | 'evidence' | 'neutral' | 'success' }> = {
  new: { label: '新卡', tone: 'ink' },
  due: { label: '到期', tone: 'evidence' },
  learning: { label: '学习中', tone: 'neutral' },
  mature: { label: '已熟练', tone: 'success' },
}

/** "明天复习" / "3 天后复习" / "已到期" */
export function scheduleLabel(card: Pick<AnkiCardItem, 'last_quality' | 'due_at'>, today: string = localDay()): string {
  if (card.last_quality == null) return '还没学过'
  const diff = dayDiff(card.due_at, today)
  if (diff === null) return '未排期'
  if (diff <= 0) return '已到期'
  if (diff === 1) return '明天复习'
  if (diff < 30) return `${diff} 天后复习`
  return `${Math.round(diff / 30)} 个月后复习`
}

export interface DeckCounts {
  total: number
  new: number
  due: number
  learning: number
  mature: number
}

export function countDeck(cards: AnkiCardItem[], now: number = Date.now()): DeckCounts {
  const c: DeckCounts = { total: cards.length, new: 0, due: 0, learning: 0, mature: 0 }
  for (const card of cards) c[stateOf(card, now)] += 1
  return c
}

export type DeckFilter = 'all' | CardState

export function filterDeck(cards: AnkiCardItem[], filter: DeckFilter, tag: string | null, query: string, now: number = Date.now()): AnkiCardItem[] {
  const q = query.trim().toLowerCase()
  return cards.filter(card => {
    if (filter !== 'all' && stateOf(card, now) !== filter) return false
    if (tag && !tagsOf(card).includes(tag)) return false
    return !q || `${card.front}\n${card.back}\n${card.tags ?? ''}`.toLowerCase().includes(q)
  })
}

export function tagCounts(cards: AnkiCardItem[]): Array<{ tag: string; count: number }> {
  const map = new Map<string, number>()
  for (const card of cards) for (const t of tagsOf(card)) map.set(t, (map.get(t) ?? 0) + 1)
  return [...map.entries()].map(([tag, count]) => ({ tag, count })).sort((a, b) => b.count - a.count || a.tag.localeCompare(b.tag, 'zh-CN'))
}

/**
 * Today's session: due reviews first (oldest due first), then up to
 * `newLimit` new cards in the order they were added.
 */
export function sessionQueue(review: AnkiCardItem[], fresh: AnkiCardItem[], newLimit = 20): AnkiCardItem[] {
  const seen = new Set<number>()
  const out: AnkiCardItem[] = []
  for (const c of [...review, ...fresh.slice(0, newLimit)]) {
    if (seen.has(c.id)) continue
    seen.add(c.id)
    out.push(c)
  }
  return out
}

/* ---------------- Grades (anki-style four buttons) ---------------- */

/**
 * Quality follows the backend's 0–5 scale, which the FSRS scheduler maps to
 * Again / Hard / Good / Easy. The hint says what happens, not a guessed date;
 * the real next date is shown after grading, from the server's answer.
 */
export interface CardGrade {
  key: 'again' | 'hard' | 'good' | 'easy'
  quality: number
  label: string
  hint: string
  hotkey: string
}

export const CARD_GRADES: readonly CardGrade[] = [
  { key: 'again', quality: 1, label: '忘了', hint: '很快再出现', hotkey: '1' },
  { key: 'hard', quality: 3, label: '模糊', hint: '间隔缩短', hotkey: '2' },
  { key: 'good', quality: 4, label: '记得', hint: '按计划推进', hotkey: '3' },
  { key: 'easy', quality: 5, label: '很熟', hint: '拉长间隔', hotkey: '4' },
]

/* ---------------- CSV ---------------- */

export function csvLooksValid(text: string): { ok: boolean; reason?: string; rows: number } {
  const lines = text.trim().split(/\r?\n/).filter(l => l.trim())
  if (lines.length === 0) return { ok: false, reason: '内容是空的', rows: 0 }
  const header = lines[0].toLowerCase()
  if (!header.includes('front') || !header.includes('back')) {
    return { ok: false, reason: '第一行需要是表头，至少包含 front 和 back 两列', rows: 0 }
  }
  return { ok: true, rows: lines.length - 1 }
}
