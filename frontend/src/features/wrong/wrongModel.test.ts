import { describe, expect, it } from 'vitest'
import type { WrongQuestionItem } from '../../services/wrongQuestionApi'
import { cardBack, countByStatus, excerpt, filterItems, isDue, sortItems, statusOf } from './wrongModel'

function wq(p: Partial<WrongQuestionItem> & { id: number }): WrongQuestionItem {
  return {
    question_id: p.id,
    content: `题目 ${p.id}`,
    chapter_title: '未分类',
    wrong_count: 1,
    mastery_status: 'not_mastered',
    review_count: 0,
    ...p,
  }
}

describe('status', () => {
  it('falls back to not mastered for unknown values', () => {
    expect(statusOf({ mastery_status: 'weird' as WrongQuestionItem['mastery_status'] })).toBe('not_mastered')
  })
  it('counts every status', () => {
    const counts = countByStatus([wq({ id: 1 }), wq({ id: 2, mastery_status: 'partial' }), wq({ id: 3, mastery_status: 'mastered' }), wq({ id: 4 })])
    expect(counts).toEqual({ not_mastered: 2, partial: 1, mastered: 1 })
  })
})

describe('isDue', () => {
  it('is due on or before today and not after', () => {
    expect(isDue({ next_review_at: '2026-09-24' }, '2026-09-25')).toBe(true)
    expect(isDue({ next_review_at: '2026-09-25' }, '2026-09-25')).toBe(true)
    expect(isDue({ next_review_at: '2026-09-26' }, '2026-09-25')).toBe(false)
    expect(isDue({ next_review_at: null }, '2026-09-25')).toBe(false)
  })
})

describe('filterItems', () => {
  const items = [
    wq({ id: 1, content: '费曼复盘的关键', knowledge_point: '费曼' }),
    wq({ id: 2, content: '间隔复习的间隔', mastery_status: 'mastered', answer: '越来越长' }),
  ]
  it('filters by status', () => {
    expect(filterItems(items, 'mastered', '').map(i => i.id)).toEqual([2])
  })
  it('searches content, answers and knowledge points case-insensitively', () => {
    expect(filterItems(items, 'all', '越来越').map(i => i.id)).toEqual([2])
    expect(filterItems(items, 'all', '费曼').map(i => i.id)).toEqual([1])
    expect(filterItems(items, 'all', '  ').length).toBe(2)
  })
})

describe('sortItems', () => {
  const items = [
    wq({ id: 1, next_review_at: '2026-09-28T00:00:00Z', wrong_count: 1, last_wrong_at: '2026-09-20T00:00:00Z' }),
    wq({ id: 2, next_review_at: null, wrong_count: 4, last_wrong_at: '2026-09-10T00:00:00Z' }),
    wq({ id: 3, next_review_at: '2026-09-22T00:00:00Z', wrong_count: 2, last_wrong_at: '2026-09-24T00:00:00Z' }),
  ]
  it('orders by next review with unscheduled items last', () => {
    expect(sortItems(items, 'due').map(i => i.id)).toEqual([3, 1, 2])
  })
  it('orders by wrong count', () => {
    expect(sortItems(items, 'wrong').map(i => i.id)).toEqual([2, 3, 1])
  })
  it('orders by most recent mistake', () => {
    expect(sortItems(items, 'recent').map(i => i.id)).toEqual([3, 1, 2])
  })
  it('does not mutate the input', () => {
    const before = items.map(i => i.id)
    sortItems(items, 'wrong')
    expect(items.map(i => i.id)).toEqual(before)
  })
})

describe('text helpers', () => {
  it('builds a card back from answer and explanation', () => {
    expect(cardBack({ answer: 'A', explanation: '因为 B' })).toBe('A\n\n解析：因为 B')
    expect(cardBack({ answer: null, explanation: null })).toBe('（待补充答案）')
  })
  it('shortens long text on one line', () => {
    expect(excerpt('a\n b   c', 60)).toBe('a b c')
    expect(excerpt('一二三四五六', 4)).toBe('一二三…')
  })
})
