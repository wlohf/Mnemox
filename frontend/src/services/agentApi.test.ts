import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('antd', () => ({
  message: {
    error: vi.fn(),
    warning: vi.fn(),
  },
}))

import {
  confirmAgentMemoryCandidate,
  getAgentCoreProfile,
  getWeeklyLearningReport,
  ignoreAgentMemoryCandidate,
  cancelAgentJob,
  confirmAgentKernelAction,
  prepareAgentKernel,
  prepareAgentKernelAction,
  runPreparedAgentKernel,
  runAgentMemoryLearning,
  streamAgentJobEvents,
} from './agentApi'

function mockJson(body: unknown) {
  const fetchMock = vi.fn(async (_url: string, _options?: RequestInit) =>
    new Response(JSON.stringify(body), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }),
  )
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

describe('agentApi memory endpoints', () => {
  beforeEach(() => {
    localStorage.clear()
    vi.restoreAllMocks()
  })

  it('normalizes wrapped core profile responses', async () => {
    mockJson({
      memory: { id: 7, memory_key: 'agent_core_profile', updated_at: '2026-06-24T00:00:00' },
      profile: { summary: [{ category: 'goal', items: ['英语听力'] }], updated_at: '2026-06-24T00:00:00' },
    })

    const profile = await getAgentCoreProfile()

    expect(profile?.id).toBe(7)
    expect(profile?.memory_key).toBe('agent_core_profile')
    expect(profile?.memory_value).toContain('英语听力')
  })

  it('posts candidate review actions with the expected body', async () => {
    const fetchMock = mockJson({ ok: true })

    await confirmAgentMemoryCandidate(42, { lock: true })
    await ignoreAgentMemoryCandidate(42, { reason: 'inaccurate' })
    await runAgentMemoryLearning()

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      '/api/agent/memory/candidates/42/confirm',
      expect.objectContaining({ method: 'POST', body: JSON.stringify({ lock: true }) }),
    )
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      '/api/agent/memory/candidates/42/ignore',
      expect.objectContaining({ method: 'POST', body: JSON.stringify({ reason: 'inaccurate' }) }),
    )
    expect(fetchMock).toHaveBeenNthCalledWith(
      3,
      '/api/agent/memory/run-learning',
      expect.objectContaining({ method: 'POST' }),
    )
  })

  it('starts, resumes and cancels durable AgentKernel jobs', async () => {
    const fetchMock = mockJson({ status: 'completed', job_id: 'job-2', next_actions: [], steps: [] })

    await prepareAgentKernel()
    await prepareAgentKernel('job-1')
    await runPreparedAgentKernel('job-2')
    await cancelAgentJob('job-2')

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      '/api/agent/kernel/jobs',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ resume_from_job_id: null, max_steps: 6 }),
      }),
    )
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      '/api/agent/kernel/jobs',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ resume_from_job_id: 'job-1', max_steps: 6 }),
      }),
    )
    expect(fetchMock).toHaveBeenNthCalledWith(
      3,
      '/api/agent/kernel/run',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ prepared_job_id: 'job-2' }),
      }),
    )
    expect(fetchMock).toHaveBeenNthCalledWith(
      4,
      '/api/agent/jobs/job-2/cancel',
      expect.objectContaining({ method: 'POST' }),
    )
  })

  it('prepares and confirms a persisted Kernel action by receipt id', async () => {
    const fetchMock = mockJson({
      status: 'created',
      job_id: 'job-2',
      draft_id: 'draft-1',
      idempotent: false,
    })

    await prepareAgentKernelAction('job-2', 'practice/matrix')
    await confirmAgentKernelAction('job-2', 'practice/matrix', 'draft-1')

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      '/api/agent/jobs/job-2/actions/practice%2Fmatrix/draft',
      expect.objectContaining({ method: 'POST' }),
    )
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      '/api/agent/jobs/job-2/actions/practice%2Fmatrix/confirm',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ draft_id: 'draft-1' }),
      }),
    )
  })

  it('requests the weekly consolidation draft in the selected time zone', async () => {
    const fetchMock = mockJson({
      time_zone: 'Asia/Shanghai',
      consolidation: { draft_key: 'weekly-consolidation:2026-08-31:abc' },
    })

    const report = await getWeeklyLearningReport('Asia/Shanghai')

    expect(report?.time_zone).toBe('Asia/Shanghai')
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/agent/weekly-report?time_zone=Asia%2FShanghai',
      expect.any(Object),
    )
  })

  it('replays and follows durable AgentKernel logs over SSE', async () => {
    const encoder = new TextEncoder()
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(encoder.encode('event: snapshot\ndata: {"type":"snapshot","job":{"id":"job-2","status":"running"}}\n\n'))
        controller.enqueue(encoder.encode('event: log\ndata: {"type":"log","log":{"id":"log-1","status":"tool","message":"step1"}}\n'))
        controller.enqueue(encoder.encode('\nevent: terminal\ndata: {"type":"terminal","job":{"id":"job-2","status":"completed"}}\n\n'))
        controller.close()
      },
    })
    const fetchMock = vi.fn(async () => new Response(body, {
      status: 200,
      headers: { 'Content-Type': 'text/event-stream' },
    }))
    vi.stubGlobal('fetch', fetchMock)
    const snapshots: Array<Record<string, unknown>> = []
    const logs: Array<Record<string, unknown>> = []
    const terminals: Array<Record<string, unknown>> = []

    const outcome = await streamAgentJobEvents('job-2', {
      onSnapshot: (job) => snapshots.push(job),
      onLog: (log) => logs.push(log),
      onTerminal: (job) => terminals.push(job),
    })

    expect(outcome).toBe('terminal')
    expect(snapshots[0]).toMatchObject({ id: 'job-2', status: 'running' })
    expect(logs[0]).toMatchObject({ id: 'log-1', status: 'tool' })
    expect(terminals[0]).toMatchObject({ id: 'job-2', status: 'completed' })
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/agent/jobs/job-2/events',
      expect.objectContaining({ credentials: 'same-origin' }),
    )
  })
})
