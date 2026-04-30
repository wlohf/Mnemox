import { create } from 'zustand'
import { getMe, login as apiLogin, type UserInfo } from '../services/authApi'
import { clearToken } from '../services/apiClient'

interface AuthState {
  user: UserInfo | null
  isAuthenticated: boolean
  isLoading: boolean
  login: (username: string, password: string) => Promise<void>
  logout: () => void
  checkAuth: () => Promise<boolean>
}

export const useAuthStore = create<AuthState>((set) => ({
  user: null,
  isAuthenticated: false,
  isLoading: true,

  login: async (username: string, password: string) => {
    set({ isLoading: true })
    try {
      await apiLogin(username, password)
      const user = await getMe()
      if (!user) {
        set({ user: null, isAuthenticated: false, isLoading: false })
        throw new Error('登录成功但获取用户信息失败，请重试')
      }
      set({ user, isAuthenticated: true, isLoading: false })
    } catch (e) {
      set({ user: null, isAuthenticated: false, isLoading: false })
      throw e
    }
  },

  logout: () => {
    clearToken()
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
      set({ user, isAuthenticated: !!user, isLoading: false })
      return !!user
    } catch {
      set({ user: null, isAuthenticated: false, isLoading: false })
      return false
    }
  },
}))
