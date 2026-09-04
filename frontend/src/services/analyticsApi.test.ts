import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('antd', () => ({
  message: {
    error: vi.fn(),
    warning: vi.fn(),
  },
}))

import { getCoachExperimentReport } from './analyticsApi'

describe('analyticsApi Coach experiment report', () => {
  beforeEach(() => {
    localStorage.clear()
    vi.restoreAllMocks()
  })

  it('loads the authenticated user-scoped A/A observation report', async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({
      enabled: true,
      experiment_id: 'coach_intervention_aa_v1',
      mode: 'aa_observation',
      policy_behavior_changed: false,
      assignment: { variant: 'control', bucket: 123 },
      period: { days: 28 },
      variants: [],
      coverage: {},
      decision_readiness: { ready: false },
      disclaimer: 'A/A',
    }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }))
    vi.stubGlobal('fetch', fetchMock)

    const report = await getCoachExperimentReport(28)

    expect(report?.enabled).toBe(true)
    expect(report?.policy_behavior_changed).toBe(false)
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/analytics/coach-experiment?days=28',
      expect.objectContaining({ credentials: 'same-origin' }),
    )
  })
})
