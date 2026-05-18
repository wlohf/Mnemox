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

  it('formats unknown errors with a fallback message', () => {
    expect(getApiErrorMessage(null, '加载失败')).toBe('加载失败')
  })
})
