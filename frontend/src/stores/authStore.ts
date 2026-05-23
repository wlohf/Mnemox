import { create } from 'zustand'
import { getMe, login as apiLogin, type UserInfo } from '../services/authApi'
import { clearToken } from '../services/apiClient'
import { clearSavedLogin, getSavedLogin, saveLoginIfAvailable } from '../services/desktopAuth'

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

export const useAuthStore = create<AuthState>((set) => ({
  user: null,
  isAuthenticated: false,
  isLoading: true,

  login: async (username: string, password: string, options: LoginOptions = {}) => {
    set({ isLoading: true })
    try {
      await apiLogin(username, password)
      const user = await getMe()
      if (!user) {
        set({ user: null, isAuthenticated: false, isLoading: false })
        throw new Error('登录成功但获取用户信息失败，请重试')
      }
      if (options.rememberPassword) {
        await saveLoginIfAvailable({
          username,
          password,
          autoLogin: options.autoLogin === true,
        })
      } else if (options.rememberPassword === false) {
        await clearSavedLogin()
      }
      set({ user, isAuthenticated: true, isLoading: false })
    } catch (e) {
      set({ user: null, isAuthenticated: false, isLoading: false })
      throw e
    }
  },

  logout: (options: LogoutOptions = {}) => {
    clearToken()
    if (options.clearSavedPassword) {
      void clearSavedLogin()
    }
    set({ user: null, isAuthenticated: false, isLoading: false })
  },

  checkAuth: async () => {
    // Skip re-check if already authenticated (avoids race conditions)
    const state = useAuthStore.getState()
    if (state.isAuthenticated && state.user) {
      set({ isLoading: false })
      return true
    }
    set({ isLoading: true })
    try {
      const user = await getMe()
      if (user) {
        set({ user, isAuthenticated: true, isLoading: false })
        return true
      }

      const savedLogin = await getSavedLogin()
      if (savedLogin?.autoLogin) {
        await useAuthStore.getState().login(savedLogin.username, savedLogin.password)
        return true
      }

      set({ user: null, isAuthenticated: false, isLoading: false })
      return false
    } catch {
      set({ user: null, isAuthenticated: false, isLoading: false })
      return false
    }
  },
}))
