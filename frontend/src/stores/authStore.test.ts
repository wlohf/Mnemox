import { beforeEach, describe, expect, it, vi } from 'vitest'

const authApiMock = vi.hoisted(() => ({
  login: vi.fn(),
  getMe: vi.fn(),
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

  it('keeps saved credentials on plain logout', () => {
    useAuthStore.getState().logout()

    expect(apiClientMock.clearToken).toHaveBeenCalled()
    expect(desktopAuthMock.clearSavedLogin).not.toHaveBeenCalled()
  })

  it('can clear saved credentials on explicit logout', () => {
    useAuthStore.getState().logout({ clearSavedPassword: true })

    expect(apiClientMock.clearToken).toHaveBeenCalled()
    expect(desktopAuthMock.clearSavedLogin).toHaveBeenCalled()
  })
})
