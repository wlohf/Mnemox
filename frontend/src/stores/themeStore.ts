import { create } from 'zustand'

export type ThemeMode = 'system' | 'warm' | 'dark'

interface ThemeStore {
  mode: ThemeMode
  setMode: (mode: ThemeMode) => void
  resolvedTheme: 'warm' | 'dark'
  bgImage: string | null       // base64 data URL
  bgOpacity: number            // 0.05 – 0.4
  setBgImage: (url: string | null) => void
  setBgOpacity: (v: number) => void
  resetToDefault: () => void
}

function getSystemTheme(): 'warm' | 'dark' {
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'warm'
}

function resolve(mode: ThemeMode): 'warm' | 'dark' {
  if (mode === 'system') return getSystemTheme()
  return mode as 'warm' | 'dark'
}

const saved = (localStorage.getItem('theme_mode') as ThemeMode) || 'system'
const savedBgImage = localStorage.getItem('bg_image') || null
const savedBgOpacity = parseFloat(localStorage.getItem('bg_opacity') || '0.15')

export const useThemeStore = create<ThemeStore>((set) => ({
  mode: saved,
  resolvedTheme: resolve(saved),
  bgImage: savedBgImage,
  bgOpacity: savedBgOpacity,
  setMode: (mode) => {
    localStorage.setItem('theme_mode', mode)
    const resolved = resolve(mode)
    document.documentElement.setAttribute('data-theme', resolved)
    set({ mode, resolvedTheme: resolved })
  },
  setBgImage: (url) => {
    if (url) localStorage.setItem('bg_image', url)
    else localStorage.removeItem('bg_image')
    set({ bgImage: url })
  },
  setBgOpacity: (v) => {
    localStorage.setItem('bg_opacity', String(v))
    set({ bgOpacity: v })
  },
  resetToDefault: () => {
    localStorage.removeItem('theme_mode')
    localStorage.removeItem('bg_image')
    localStorage.removeItem('bg_opacity')
    const resolved = resolve('system')
    document.documentElement.setAttribute('data-theme', resolved)
    set({ mode: 'system', resolvedTheme: resolved, bgImage: null, bgOpacity: 0.15 })
  }
}))

// Init on load
const initMode = (localStorage.getItem('theme_mode') as ThemeMode) || 'system'
document.documentElement.setAttribute('data-theme', resolve(initMode))

// Listen for system changes
window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
  const { mode, setMode } = useThemeStore.getState()
  if (mode === 'system') setMode('system') // triggers resolve again
})
