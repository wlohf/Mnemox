import type { WrongQuestionItem } from '../../services/wrongQuestionApi'
import { localDay, toLocalDay } from '../../lib/dates'

/*
 * View model for 错题本: labels, filtering, ordering and "is it due" rules.
 * Pure functions only, so the page stays thin and this stays testable.
 */

export type MasteryStatus = 'not_mastered' | 'partial' | 'mastered'
export type StatusFilter = 'all' | MasteryStatus
export type SortKey = 'recent' | 'due' | 'wrong'

export const STATUS_META: Record<MasteryStatus, { label: string; tone: 'danger' | 'warning' | 'success'; color: string }> = {
  not_mastered: { label: '未掌握', tone: 'danger', color: 'var(--mx-danger)' },
  partial: { label: '部分掌握', tone: 'warning', color: 'var(--mx-warning)' },
  mastered: { label: '已掌握', tone: 'success', color: 'var(--mx-success)' },
}

export const STATUS_ORDER: MasteryStatus[] = ['not_mastered', 'partial', 'mastered']

export const QUESTION_TYPES: Array<{ value: string; label: string }> = [
  { value: 'short_answer', label: '简答题' },
  { value: 'choice', label: '选择题' },
  { value: 'fill_blank', label: '填空题' },
  { value: 'essay', label: '论述题' },
]

export const SORTS: Array<{ value: SortKey; label: string }> = [
  { value: 'due', label: '按复习时间' },
  { value: 'recent', label: '最近错的' },
  { value: 'wrong', label: '错得最多' },
]

export function statusOf(item: Pick<WrongQuestionItem, 'mastery_status'>): MasteryStatus {
  return item.mastery_status in STATUS_META ? item.mastery_status : 'not_mastered'
}

export function questionTypeLabel(type: string | null | undefined): string {
  return QUESTION_TYPES.find(t => t.value === type)?.label ?? '简答题'
}

/** Due when the next review falls on or before today (local calendar). */
export function isDue(item: Pick<WrongQuestionItem, 'next_review_at'>, today: string = localDay()): boolean {
  const day = toLocalDay(item.next_review_at)
  return day !== null && day <= today
}

export function countByStatus(items: WrongQuestionItem[]): Record<MasteryStatus, number> {
  const counts: Record<MasteryStatus, number> = { not_mastered: 0, partial: 0, mastered: 0 }
  for (const it of items) counts[statusOf(it)] += 1
  return counts
}

function haystack(it: WrongQuestionItem): string {
  return [it.content, it.answer, it.explanation, it.knowledge_point, it.chapter_title].filter(Boolean).join('\n').toLowerCase()
}

export function filterItems(items: WrongQuestionItem[], status: StatusFilter, query: string): WrongQuestionItem[] {
  const q = query.trim().toLowerCase()
  return items.filter(it => (status === 'all' || statusOf(it) === status) && (!q || haystack(it).includes(q)))
}

const time = (iso: string | null | undefined, fallback: number) => {
  if (!iso) return fallback
  const t = Date.parse(iso)
  return Number.isNaN(t) ? fallback : t
}

export function sortItems(items: WrongQuestionItem[], sort: SortKey): WrongQuestionItem[] {
  const list = items.slice()
  if (sort === 'due') {
    // Soonest review first; items with no schedule go last.
    list.sort((a, b) => time(a.next_review_at, Infinity) - time(b.next_review_at, Infinity) || b.id - a.id)
  } else if (sort === 'wrong') {
    list.sort((a, b) => (b.wrong_count ?? 0) - (a.wrong_count ?? 0) || time(b.last_wrong_at, 0) - time(a.last_wrong_at, 0) || b.id - a.id)
  } else {
    list.sort((a, b) => time(b.last_wrong_at ?? b.created_at, 0) - time(a.last_wrong_at ?? a.created_at, 0) || b.id - a.id)
  }
  return list
}

/** Back of a flashcard made from a wrong question. */
export function cardBack(item: Pick<WrongQuestionItem, 'answer' | 'explanation'>): string {
  const parts = [item.answer?.trim(), item.explanation?.trim() ? `解析：${item.explanation.trim()}` : null].filter(Boolean)
  return parts.length ? parts.join('\n\n') : '（待补充答案）'
}

/** Short, single-line form of a question for labels and handoffs. */
export function excerpt(text: string, max = 60): string {
  const flat = text.replace(/\s+/g, ' ').trim()
  return flat.length > max ? `${flat.slice(0, max - 1)}…` : flat
}
