import { describe, expect, it } from 'vitest'
import type { ConceptState, ConceptSummary, LearningRecommendation } from '../../services/learnerModelApi'
import {
  basisOf,
  chapterMatrix,
  filterConcepts,
  levelOf,
  overviewOf,
  pct01,
  recommendationRoute,
  riskLabel,
  sortConcepts,
} from './masteryModel'

function concept(p: Partial<ConceptSummary> & { id: number }): ConceptSummary {
  return {
    name: `概念${p.id}`,
    mastery: 0,
    mastery_source: 'user_concept_state',
    mastery_model_version: 'v1',
    source: 'material_extract',
    link_count: 1,
    review_status: 'confirmed',
    ...p,
  }
}

describe('levels', () => {
  it('maps 0–100 into five steps, with 0 reserved for no evidence', () => {
    expect([10, 30, 50, 70, 85, 100].map(v => levelOf(v))).toEqual([1, 2, 3, 4, 5, 5])
    expect(levelOf(80, false)).toBe(0)
    expect(levelOf(-5)).toBe(1)
  })
  it('turns probabilities into percents and labels risk', () => {
    expect(pct01(0.456)).toBe(46)
    expect(riskLabel(0.7).tone).toBe('danger')
    expect(riskLabel(0.4).tone).toBe('warning')
    expect(riskLabel(0.1).tone).toBe('success')
    expect(riskLabel(0).tone).toBe('neutral')
  })
})

describe('concept list', () => {
  const list = [
    concept({ id: 1, name: '间隔效应', mastery: 80 }),
    concept({ id: 2, name: '主动回忆', mastery: 30 }),
    concept({ id: 3, name: '讲义标题', review_status: 'pending' }),
    concept({ id: 4, name: '错的', review_status: 'rejected' }),
  ]
  it('filters by weak, pending and text', () => {
    expect(filterConcepts(list, 'weak', '').map(c => c.id)).toEqual([2])
    expect(filterConcepts(list, 'pending', '').map(c => c.id)).toEqual([3])
    expect(filterConcepts(list, 'all', '回忆').map(c => c.id)).toEqual([2])
  })
  it('sorts confirmed weakest first, then pending, then rejected', () => {
    expect(sortConcepts(list).map(c => c.id)).toEqual([2, 1, 3, 4])
  })
  it('summarises only confirmed concepts', () => {
    expect(overviewOf(list)).toEqual({ confirmed: 2, pending: 1, average: 55, weak: 1 })
    expect(overviewOf([]).average).toBeNull()
  })
})

describe('chapterMatrix', () => {
  it('normalises chapter mastery into rows with levels', () => {
    const m = chapterMatrix({
      materials: [{ material_id: 1, material_title: '讲义', average_mastery: 53.3, chapter_count: 1, chapters: [{ chapter_id: 9, chapter_title: '费曼', mastery_level: 45, band: 'weak' }] }],
      weak_points: [],
    } as never)
    expect(m).toEqual([{ id: 1, title: '讲义', average: 53, chapters: [{ id: 9, title: '费曼', mastery: 45, level: 2 }] }])
    expect(chapterMatrix(null)).toEqual([])
  })
})

describe('recommendations and basis', () => {
  it('routes each recommendation type', () => {
    const r = (task_type: LearningRecommendation['task_type']) => ({ task_type, concept_name: 'RRF', suggested_action: '练一题' }) as LearningRecommendation
    expect(recommendationRoute(r('review_due'))).toBe('/review')
    expect(recommendationRoute(r('continue_goal'))).toBe('/goals')
    expect(recommendationRoute(r('prerequisite_gap'))).toContain('context=RRF')
  })
  it('explains the estimate in plain words', () => {
    const st = (s: Record<string, unknown>, manual = false) => ({ explanation_summary: s, manual_override: manual ? { active: true } : null }) as unknown as ConceptState
    expect(basisOf(st({}))).toContain('还没有')
    expect(basisOf(st({ indirect_signal_count: 3 }))).toContain('间接信号')
    expect(basisOf(st({ direct_evidence_count: 4, indirect_signal_count: 1 }))).toBe('根据 4 条直接证据和 1 条间接信号估计。')
    expect(basisOf(st({}, true))).toContain('手动修正')
  })
})
