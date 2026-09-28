import { describe, expect, it } from 'vitest'
import type { MemoryConflict, MemoryDeclaration, MemoryItem } from '../../services/memoryApi'
import {
  categoryLabel,
  confidenceLabel,
  evidenceLines,
  groupMemories,
  isUserFacing,
  stagedWithoutConflicts,
  stateOf,
  timeline,
  viewOf,
} from './memoryModel'

function mem(p: Partial<MemoryItem> & { id: number }): MemoryItem {
  return { memory_key: `k${p.id}`, memory_value: `v${p.id}`, category: 'style', confidence: 0.8, status: 'active', review_status: 'confirmed', ...p }
}

describe('state and visibility', () => {
  it('derives a single state from status and review status', () => {
    expect(stateOf({ status: 'active', review_status: 'confirmed' })).toBe('active')
    expect(stateOf({ status: 'staged', review_status: 'staged' })).toBe('staged')
    expect(stateOf({ status: 'active', review_status: 'inaccurate' })).toBe('ignored')
    expect(stateOf({ status: 'expired', review_status: 'confirmed' })).toBe('expired')
    expect(viewOf(mem({ id: 1, status: 'superseded' }))).toBe('archive')
  })
  it('hides system rows and the aggregate profile', () => {
    expect(isUserFacing({ category: 'system', memory_type: 'semantic', memory_key: 'x' })).toBe(false)
    expect(isUserFacing({ category: 'system', memory_type: 'profile', memory_key: 'agent_learning_profile' })).toBe(false)
    expect(isUserFacing({ category: 'goal', memory_type: 'semantic', memory_key: 'demo_goal' })).toBe(true)
  })
})

describe('groupMemories', () => {
  it('orders groups meaningfully and merges synonymous categories', () => {
    const groups = groupMemories([
      mem({ id: 1, category: 'pattern' }),
      mem({ id: 2, category: 'goal' }),
      mem({ id: 3, category: 'preference' }),
      mem({ id: 4, category: 'style', is_locked: 1, confidence: 0.5 }),
    ])
    expect(groups.map(g => g.label)).toEqual(['目标', '偏好与风格', '学习规律'])
    expect(groups[1].items.map(m => m.id)).toEqual([4, 3])
  })
  it('labels unknown categories as other', () => {
    expect(categoryLabel('whatever')).toBe('其他')
  })
})

describe('stagedWithoutConflicts', () => {
  it('does not repeat candidates already shown in a conflict', () => {
    const items = [mem({ id: 1, status: 'staged', review_status: 'staged' }), mem({ id: 2, status: 'staged', review_status: 'staged' })]
    const conflicts = [{ candidate_memory_id: 2 } as MemoryConflict]
    expect(stagedWithoutConflicts(items, conflicts).map(m => m.id)).toEqual([1])
  })
})

describe('provenance helpers', () => {
  it('describes confidence in words', () => {
    expect(confidenceLabel(0.9)).toBe('很有把握')
    expect(confidenceLabel(0.7)).toBe('比较有把握')
    expect(confidenceLabel(0.2)).toBe('把握不大')
  })
  it('turns aggregate evidence into readable lines', () => {
    expect(evidenceLines([{ kind: 'aggregate', event_type: 'pomodoro.started', duration_seconds: 1500 }])).toEqual(['pomodoro.started 累计 25 分钟'])
    expect(evidenceLines([{ kind: 'aggregate', category: 'practice', count: 2 }])).toEqual(['practice 类行为 2 次'])
    expect(evidenceLines('直接引用')).toEqual(['直接引用'])
    expect(evidenceLines(null)).toEqual([])
  })
  it('orders declarations newest first', () => {
    const d = (id: number, at: string) => ({ id, observed_at: at, created_at: at }) as MemoryDeclaration
    expect(timeline([d(1, '2026-09-01'), d(2, '2026-09-20'), d(3, '2026-09-10')]).map(x => x.id)).toEqual([2, 3, 1])
  })
})
