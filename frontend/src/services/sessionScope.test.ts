import { afterEach, describe, expect, it, vi } from 'vitest'
vi.mock('antd', () => ({ message: { error: vi.fn(), warning: vi.fn() } }))
import { apiFetch, scopedApiFetch } from './apiClient'
import { captureApiSession, setApiSessionUser, SESSION_INVALIDATED_EVENT } from './sessionScope'

afterEach(() => { setApiSessionUser(null); vi.unstubAllGlobals() })

describe('request session fencing', () => {
  it('attaches the expected identity to authenticated requests', async () => {
    setApiSessionUser(101)
    const request = vi.fn<typeof fetch>(async () => new Response('{"ok":true}'))
    vi.stubGlobal('fetch', request)
    await apiFetch('/api/notes')
    expect(new Headers(request.mock.calls[0][1]?.headers).get('X-Mnemox-User-Id')).toBe('101')
  })

  it('aborts old requests and rejects late responses even if transport ignores cancellation', async () => {
    setApiSessionUser(101)
    const scope = captureApiSession()
    let finish!: (response: Response) => void
    vi.stubGlobal('fetch', vi.fn(() => new Promise<Response>((resolve) => { finish = resolve })))
    const request = apiFetch('/api/notes')
    const assertion = expect(request).rejects.toMatchObject({ name: 'AbortError' })
    setApiSessionUser(102)
    expect(scope.signal.aborted).toBe(true)
    finish(new Response('[{"title":"private A"}]'))
    await assertion
  })

  it('does not issue a delayed A operation using B cookie', async () => {
    setApiSessionUser(101)
    const oldRequest = scopedApiFetch()
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
    setApiSessionUser(102)
    await expect(oldRequest('/api/notes', { method: 'POST', body: '{"title":"private A"}' })).rejects.toMatchObject({ name: 'AbortError' })
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('invalidates a stale tab on cross-tab login/logout without revoking the new session', () => {
    setApiSessionUser(101)
    const scope = captureApiSession()
    const invalidated = vi.fn()
    window.addEventListener(SESSION_INVALIDATED_EVENT, invalidated)
    window.dispatchEvent(new StorageEvent('storage', { key: 'mnemox.session-change', newValue: 'new-generation' }))
    expect(scope.signal.aborted).toBe(true)
    expect(invalidated).toHaveBeenCalledOnce()
    window.removeEventListener(SESSION_INVALIDATED_EVENT, invalidated)
  })

  it('invalidates local state on a server-detected cookie mismatch', async () => {
    setApiSessionUser(101)
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ detail: { code: 'SESSION_USER_MISMATCH', message: '账号已变化' } }), { status: 409 })))
    const invalidated = vi.fn()
    window.addEventListener(SESSION_INVALIDATED_EVENT, invalidated)
    await expect(apiFetch('/api/notes')).rejects.toMatchObject({ code: 'SESSION_USER_MISMATCH', status: 409 })
    expect(invalidated).toHaveBeenCalledOnce()
    window.removeEventListener(SESSION_INVALIDATED_EVENT, invalidated)
  })
})
