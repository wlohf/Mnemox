import { describe, expect, it } from 'vitest'
import { evidenceCategoryLabel, evidenceTypeLabel, explanationRows } from './learnerModelDisplay'

describe('learner model display mappings', () => {
  it('distinguishes direct, indirect, manual and legacy evidence', () => {
    expect(evidenceCategoryLabel('direct')).toBe('直接证据')
    expect(evidenceCategoryLabel('indirect')).toBe('间接信号')
    expect(evidenceCategoryLabel('manual')).toBe('人工修正')
    expect(evidenceCategoryLabel('legacy')).toBe('Legacy 来源')
  })

  it('names review evidence and renders explanation facts', () => {
    expect(evidenceTypeLabel('review_result')).toBe('复习结果')
    expect(explanationRows({ basis: 'direct_evidence', direct_evidence_count: 4 })).toEqual([
      ['计算依据', '直接证据'],
      ['直接证据', '4 条'],
    ])
  })
})
