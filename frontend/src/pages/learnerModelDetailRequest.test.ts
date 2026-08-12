import { describe, expect, it } from 'vitest'

import { canApplyConceptDetail } from './learnerModelDetailRequest'

describe('learner model detail request guards', () => {
  it('accepts only the latest response for the selected concept', () => {
    expect(canApplyConceptDetail(4, 4, 12, 12)).toBe(true)
    expect(canApplyConceptDetail(3, 4, 12, 12)).toBe(false)
    expect(canApplyConceptDetail(4, 4, 12, 13)).toBe(false)
    expect(canApplyConceptDetail(4, 4, 12, null)).toBe(false)
  })
})
