import { create } from 'zustand'
import { getMe, login as apiLogin, logoutSession, type UserInfo } from '../services/authApi'
import { clearToken } from '../services/apiClient'
import { clearSavedLogin, getSavedLogin, saveLoginIfAvailable } from '../services/desktopAuth'
import { closeStudyDatabase, openStudyDatabase } from '../db/studyDb'
import { syncEngine } from '../sync/SyncEngine'
import { announceSessionChange, SESSION_INVALIDATED_EVENT, setApiSessionUser } from '../services/sessionScope'

interface LoginOptions {
  rememberPassword?: boolean
  autoLogin?: boolean
}

interface LogoutOptions {
  clearSavedPassword?: boolean
}

interface AuthState {
  user: UserInfo | null
  isAuthenticated: boolean
  isLoading: boolean
  login: (username: string, password: string, options?: LoginOptions) => Promise<void>
  logout: (options?: LogoutOptions) => void
  checkAuth: () => Promise<boolean>
}

let generation = 0
let authCheck: Promise<boolean> | null = null
function checkAuthOnce(action: () => Promise<boolean>): Promise<boolean> {
  if (authCheck) return authCheck
  const result = action().finally(() => { if (authCheck === result) authCheck = null })
  authCheck = result
  return result
}
// Serialize cookie-changing requests: an old logout response must not erase a new login.
let cookieMutation: Promise<unknown> = Promise.resolve()
function mutateCookie<T>(action: () => Promise<T>): Promise<T> {
  const result = cookieMutation.then(action)
  cookieMutation = result.catch(() => undefined)
  return result
}

function suspendAccount(): number {
  ++generation
  authCheck = null
  setApiSessionUser(null)
  syncEngine.stop()
  closeStudyDatabase()
  return generation
}

function assertGeneration(expected: number): void {
  if (generation !== expected) throw new DOMException('登录操作已取消', 'AbortError')
}

export const useAuthStore = create<AuthState>((set) => ({
  user: null,
  isAuthenticated: false,
  isLoading: true,

  login: async (username: string, password: string, options: LoginOptions = {}) => {
    const current = suspendAccount()
    announceSessionChange()
    set({ user: null, isAuthenticated: false, isLoading: true })
    try {
      await mutateCookie(async () => {
        assertGeneration(current)
        await apiLogin(username, password)
      })
      assertGeneration(current)
      const user = await getMe()
      assertGeneration(current)
      if (!user) throw new Error('登录成功但获取用户信息失败，请重试')
      if (options.rememberPassword) {
        await saveLoginIfAvailable({ username, password, autoLogin: options.autoLogin === true })
      } else if (options.rememberPassword === false) {
        await clearSavedLogin()
      }
      assertGeneration(current)
      await openStudyDatabase(user)
      assertGeneration(current)
      setApiSessionUser(user.id)
      set({ user, isAuthenticated: true, isLoading: false })
    } catch (e) {
      if (generation === current) {
        suspendAccount()
        set({ user: null, isAuthenticated: false, isLoading: false })
      }
      throw e
    }
  },

  logout: (options: LogoutOptions = {}) => {
    // Capture the old identity before suspending, to reject cross-tab cookie skew.
    const previousUserId = useAuthStore.getState().user?.id
    const revoke = () => logoutSession(previousUserId)
    const current = suspendAccount()
    announceSessionChange()
    clearToken()
    void mutateCookie(revoke)
    if (options.clearSavedPassword) void clearSavedLogin()
    if (generation === current) set({ user: null, isAuthenticated: false, isLoading: false })
  },

  checkAuth: () => checkAuthOnce(async () => {
    const state = useAuthStore.getState()
    if (state.isAuthenticated && state.user) {
      set({ isLoading: false })
      return true
    }
    const current = generation
    set({ isLoading: true })
    try {
      await cookieMutation
      assertGeneration(current)
      const user = await getMe()
      assertGeneration(current)
      if (user) {
        await openStudyDatabase(user)
        assertGeneration(current)
        setApiSessionUser(user.id)
        set({ user, isAuthenticated: true, isLoading: false })
        return true
      }
      const savedLogin = await getSavedLogin()
      assertGeneration(current)
      if (savedLogin?.autoLogin) {
        await useAuthStore.getState().login(savedLogin.username, savedLogin.password)
        return true
      }
      suspendAccount()
      set({ user: null, isAuthenticated: false, isLoading: false })
      return false
    } catch {
      if (generation === current) {
        suspendAccount()
        set({ user: null, isAuthenticated: false, isLoading: false })
      }
      return false
    }
  }),
}))

window.addEventListener(SESSION_INVALIDATED_EVENT, () => {
  suspendAccount()
  // Another tab owns the cookie now. Never call the server logout on its behalf.
  useAuthStore.setState({ user: null, isAuthenticated: false, isLoading: false })
})
