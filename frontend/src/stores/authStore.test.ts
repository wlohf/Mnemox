import 'fake-indexeddb/auto'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const authApiMock = vi.hoisted(() => ({
  login: vi.fn(),
  getMe: vi.fn(),
  logoutSession: vi.fn().mockResolvedValue(undefined),
}))

const apiClientMock = vi.hoisted(() => ({
  clearToken: vi.fn(),
}))

const desktopAuthMock = vi.hoisted(() => ({
  getSavedLogin: vi.fn(),
  saveLoginIfAvailable: vi.fn(),
  clearSavedLogin: vi.fn(),
}))

vi.mock('../services/authApi', () => authApiMock)
vi.mock('../services/apiClient', () => apiClientMock)
vi.mock('../services/desktopAuth', () => desktopAuthMock)

import { useAuthStore } from './authStore'

describe('authStore desktop saved login', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    useAuthStore.setState({
      user: null,
      isAuthenticated: false,
      isLoading: true,
    })
  })

  it('saves desktop credentials when remember password is enabled', async () => {
    authApiMock.login.mockResolvedValue('token')
    authApiMock.getMe.mockResolvedValue({
      id: 1,
      username: 'alice',
      email: 'alice@example.com',
      is_active: true,
      created_at: '2026-05-23',
    })

    await useAuthStore.getState().login('alice', 'secret', {
      rememberPassword: true,
      autoLogin: true,
    })

    expect(desktopAuthMock.saveLoginIfAvailable).toHaveBeenCalledWith({
      username: 'alice',
      password: 'secret',
      autoLogin: true,
    })
    expect(useAuthStore.getState().isAuthenticated).toBe(true)
  })

  it('uses auto-login credentials when token auth is absent', async () => {
    authApiMock.getMe.mockResolvedValueOnce(null).mockResolvedValueOnce({
      id: 2,
      username: 'bob',
      email: 'bob@example.com',
      is_active: true,
      created_at: '2026-05-23',
    })
    authApiMock.login.mockResolvedValue('token')
    desktopAuthMock.getSavedLogin.mockResolvedValue({
      username: 'bob',
      password: 'secret',
      autoLogin: true,
    })

    await expect(useAuthStore.getState().checkAuth()).resolves.toBe(true)

    expect(authApiMock.login).toHaveBeenCalledWith('bob', 'secret')
    expect(useAuthStore.getState().user?.username).toBe('bob')
  })

  it('keeps saved credentials on plain logout', async () => {
    useAuthStore.getState().logout()

    expect(apiClientMock.clearToken).toHaveBeenCalled()
    await vi.waitFor(() => expect(authApiMock.logoutSession).toHaveBeenCalled())
    expect(desktopAuthMock.clearSavedLogin).not.toHaveBeenCalled()
  })

  it('can clear saved credentials on explicit logout', async () => {
    useAuthStore.getState().logout({ clearSavedPassword: true })

    expect(apiClientMock.clearToken).toHaveBeenCalled()
    await vi.waitFor(() => expect(authApiMock.logoutSession).toHaveBeenCalled())
    expect(desktopAuthMock.clearSavedLogin).toHaveBeenCalled()
  })

  it('coalesces concurrent auth checks before opening the account database', async () => {
    authApiMock.getMe.mockResolvedValue({ id: 3, username: 'carol', created_at: '2026-09-12' })
    const [first, second] = await Promise.all([
      useAuthStore.getState().checkAuth(), useAuthStore.getState().checkAuth(),
    ])
    expect(first && second).toBe(true)
    expect(authApiMock.getMe).toHaveBeenCalledOnce()
  })

  it('does not resurrect a login after logout while getMe is pending', async () => {
    let finish!: (user: unknown) => void
    authApiMock.getMe.mockImplementationOnce(() => new Promise((resolve) => { finish = resolve }))
    const login = useAuthStore.getState().login('alice', 'secret')
    const rejected = expect(login).rejects.toMatchObject({ name: 'AbortError' })
    await vi.waitFor(() => expect(finish).toBeDefined())
    useAuthStore.getState().logout()
    finish({ id: 1, username: 'alice', created_at: '2026-09-12' })
    await rejected
    expect(useAuthStore.getState().isAuthenticated).toBe(false)
  })

  it('waits for the old cookie logout before sending the next login', async () => {
    let finish!: () => void
    authApiMock.logoutSession.mockImplementationOnce(() => new Promise<void>((resolve) => { finish = resolve }))
    useAuthStore.getState().logout()
    await vi.waitFor(() => expect(finish).toBeDefined())
    authApiMock.getMe.mockResolvedValue({ id: 2, username: 'bob', created_at: '2026-09-12' })
    const login = useAuthStore.getState().login('bob', 'secret')
    await Promise.resolve()
    expect(authApiMock.login).not.toHaveBeenCalled()
    finish(); await login
    expect(useAuthStore.getState().user?.id).toBe(2)
  })
})
