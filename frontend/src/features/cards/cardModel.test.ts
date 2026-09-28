import { describe, expect, it } from 'vitest'
import type { AnkiCardItem } from '../../services/ankiApi'
import {
  CARD_GRADES,
  countDeck,
  csvLooksValid,
  filterDeck,
  joinTags,
  scheduleLabel,
  sessionQueue,
  stateOf,
  tagCounts,
  tagsOf,
} from './cardModel'

const NOW = Date.parse('2026-09-25T12:00:00Z')

function card(p: Partial<AnkiCardItem> & { id: number }): AnkiCardItem {
  return {
    front: `正面 ${p.id}`,
    back: `背面 ${p.id}`,
    source: 'manual',
    interval_days: 1,
    ease_factor: 250,
    repetitions: 0,
    last_quality: null,
    due_at: '2026-09-25T00:00:00Z',
    ...p,
  }
}

describe('tags', () => {
  it('splits on both comma styles and trims', () => {
    expect(tagsOf({ tags: 'Demo， 主动学习,,费曼 ' })).toEqual(['Demo', '主动学习', '费曼'])
    expect(tagsOf({ tags: null })).toEqual([])
  })
  it('joins unique tags', () => {
    expect(joinTags(['a', ' b', 'a', ''])).toBe('a,b')
  })
  it('counts tags across cards, most used first', () => {
    expect(tagCounts([card({ id: 1, tags: 'x,y' }), card({ id: 2, tags: 'y' })])).toEqual([
      { tag: 'y', count: 2 },
      { tag: 'x', count: 1 },
    ])
  })
})

describe('stateOf', () => {
  it('classifies cards by review history and schedule', () => {
    expect(stateOf(card({ id: 1 }), NOW)).toBe('new')
    expect(stateOf(card({ id: 2, last_quality: 4, due_at: '2026-09-24T00:00:00Z' }), NOW)).toBe('due')
    expect(stateOf(card({ id: 3, last_quality: 4, due_at: '2026-09-30T00:00:00Z', interval_days: 5 }), NOW)).toBe('learning')
    expect(stateOf(card({ id: 4, last_quality: 5, due_at: '2026-11-30T00:00:00Z', interval_days: 40 }), NOW)).toBe('mature')
  })
  it('counts a deck', () => {
    const counts = countDeck([card({ id: 1 }), card({ id: 2, last_quality: 4, due_at: '2026-09-20T00:00:00Z' })], NOW)
    expect(counts).toEqual({ total: 2, new: 1, due: 1, learning: 0, mature: 0 })
  })
})

describe('scheduleLabel', () => {
  it('describes the next review in plain words', () => {
    expect(scheduleLabel({ last_quality: null, due_at: null }, '2026-09-25')).toBe('还没学过')
    expect(scheduleLabel({ last_quality: 4, due_at: '2026-09-25' }, '2026-09-25')).toBe('已到期')
    expect(scheduleLabel({ last_quality: 4, due_at: '2026-09-26' }, '2026-09-25')).toBe('明天复习')
    expect(scheduleLabel({ last_quality: 4, due_at: '2026-10-05' }, '2026-09-25')).toBe('10 天后复习')
  })
})

describe('filterDeck', () => {
  const deck = [card({ id: 1, tags: '费曼', front: '费曼复盘是什么' }), card({ id: 2, last_quality: 4, due_at: '2026-09-20T00:00:00Z', tags: '记忆' })]
  it('filters by state, tag and text', () => {
    expect(filterDeck(deck, 'due', null, '', NOW).map(c => c.id)).toEqual([2])
    expect(filterDeck(deck, 'all', '费曼', '', NOW).map(c => c.id)).toEqual([1])
    expect(filterDeck(deck, 'all', null, '复盘', NOW).map(c => c.id)).toEqual([1])
  })
})

describe('sessionQueue', () => {
  it('puts due reviews before new cards, caps new cards and dedupes', () => {
    const review = [card({ id: 9, last_quality: 3 })]
    const fresh = [card({ id: 1 }), card({ id: 2 }), card({ id: 9 })]
    expect(sessionQueue(review, fresh, 2).map(c => c.id)).toEqual([9, 1, 2])
  })
})

describe('CARD_GRADES', () => {
  it('uses the backend quality scale in ascending order with unique hotkeys', () => {
    expect(CARD_GRADES.map(g => g.quality)).toEqual([1, 3, 4, 5])
    expect(new Set(CARD_GRADES.map(g => g.hotkey)).size).toBe(4)
  })
})

describe('csvLooksValid', () => {
  it('requires a header with front and back', () => {
    expect(csvLooksValid('front,back\n问,答\n问2,答2')).toEqual({ ok: true, rows: 2 })
    expect(csvLooksValid('问,答').ok).toBe(false)
    expect(csvLooksValid('  ').ok).toBe(false)
  })
})
