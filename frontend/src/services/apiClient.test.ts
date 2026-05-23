import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('antd', () => ({
  message: {
    error: vi.fn(),
    warning: vi.fn(),
  },
}))

import { apiFetch, getApiErrorMessage } from './apiClient'
import { getDashboard } from './learningApi'
import { getAllProviders } from './aiSettingsApi'
import { startPomodoro } from './pomodoroApi'
import { listConversations } from './conversationApi'
import { listGoals } from './goalApi'
import { draftAgentWrite } from './agentApi'
import { getCurrentQuote } from './motivationApi'
import { listReviewTasks } from './reviewApi'

function mockFetchResponse(status: number, body: unknown) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () =>
      new Response(JSON.stringify(body), {
        status,
        headers: { 'Content-Type': 'application/json' },
      }),
    ),
  )
}

describe('apiFetch error handling', () => {
  beforeEach(() => {
    localStorage.clear()
    vi.restoreAllMocks()
  })

  it('throws a readable API error parsed from detail.message', async () => {
    mockFetchResponse(400, {
      detail: {
        code: 'AI_PROVIDER_NOT_CONFIGURED',
        message: 'AI 提供商未配置',
      },
    })

    await expect(apiFetch('/api/fail')).rejects.toMatchObject({
      status: 400,
      code: 'AI_PROVIDER_NOT_CONFIGURED',
      message: 'AI 提供商未配置',
    })
  })

  it('lets service APIs propagate failures instead of returning null', async () => {
    mockFetchResponse(500, { detail: '学习数据加载失败' })

    await expect(getDashboard()).rejects.toMatchObject({
      status: 500,
      message: '学习数据加载失败',
    })
  })

  it('does not turn AI settings failures into empty data', async () => {
    mockFetchResponse(503, { detail: 'AI 设置服务不可用' })

    await expect(getAllProviders()).rejects.toMatchObject({
      status: 503,
      message: 'AI 设置服务不可用',
    })
  })

  it('does not turn pomodoro failures into null', async () => {
    mockFetchResponse(500, { detail: '番茄钟服务失败' })

    await expect(startPomodoro('专注学习', 25)).rejects.toMatchObject({
      status: 500,
      message: '番茄钟服务失败',
    })
  })

  it('does not turn conversation list failures into an empty list', async () => {
    mockFetchResponse(503, { detail: '对话服务不可用' })

    await expect(listConversations()).rejects.toMatchObject({
      status: 503,
      message: '对话服务不可用',
    })
  })

  it('does not turn goal list failures into an empty list', async () => {
    mockFetchResponse(500, { detail: '目标服务失败' })

    await expect(listGoals()).rejects.toMatchObject({
      status: 500,
      message: '目标服务失败',
    })
  })

  it('does not turn agent draft failures into null', async () => {
    mockFetchResponse(503, { detail: 'Agent 服务不可用' })

    await expect(draftAgentWrite('帮我写个计划')).rejects.toMatchObject({
      status: 503,
      message: 'Agent 服务不可用',
    })
  })

  it('does not turn motivation current quote failures into null', async () => {
    mockFetchResponse(500, { detail: '激励语录服务失败' })

    await expect(getCurrentQuote()).rejects.toMatchObject({
      status: 500,
      message: '激励语录服务失败',
    })
  })

  it('does not turn review task failures into an empty list', async () => {
    mockFetchResponse(500, { detail: '复习服务失败' })

    await expect(listReviewTasks()).rejects.toMatchObject({
      status: 500,
      message: '复习服务失败',
    })
  })

  it('formats unknown errors with a fallback message', () => {
    expect(getApiErrorMessage(null, '加载失败')).toBe('加载失败')
  })

  it('wraps network failures with a readable API error', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => {
      throw new TypeError('Failed to fetch')
    }))

    await expect(apiFetch('/api/fail')).rejects.toMatchObject({
      code: 'NETWORK_ERROR',
      message: '后端服务不可用，请确认 Mnemox 后端已启动',
    })
  })
})
