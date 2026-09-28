import { create } from 'zustand'

/*
 * Theme preference.
 *
 * `mode` keeps the persisted legacy values ('warm' = light) so existing users
 * keep their choice. The resolved theme is written to two attributes:
 *   data-mx-theme="light|dark"  → design tokens (design/tokens.css)
 *   data-theme="warm|dark"      → legacy screens still on index.css
 */
export type ThemeMode = 'system' | 'warm' | 'dark'
export type ResolvedTheme = 'warm' | 'dark'

interface ThemeStore {
  mode: ThemeMode
  resolvedTheme: ResolvedTheme
  setMode: (mode: ThemeMode, options?: { animate?: boolean }) => void
  toggle: () => void
  bgImage: string | null
  bgOpacity: number // 0.05 – 0.4
  setBgImage: (url: string | null) => void
  setBgOpacity: (v: number) => void
  resetToDefault: () => void
}

const MODE_KEY = 'theme_mode'
const BG_IMAGE_KEY = 'bg_image'
const BG_OPACITY_KEY = 'bg_opacity'

function systemPrefersDark(): boolean {
  return typeof window !== 'undefined' && window.matchMedia('(prefers-color-scheme: dark)').matches
}

function resolve(mode: ThemeMode): ResolvedTheme {
  if (mode === 'system') return systemPrefersDark() ? 'dark' : 'warm'
  return mode
}

function readMode(): ThemeMode {
  const raw = localStorage.getItem(MODE_KEY)
  return raw === 'system' || raw === 'dark' || raw === 'warm' ? raw : 'warm'
}

function applyToDocument(theme: ResolvedTheme) {
  const root = document.documentElement
  root.setAttribute('data-theme', theme)
  root.setAttribute('data-mx-theme', theme === 'dark' ? 'dark' : 'light')
  root.style.colorScheme = theme === 'dark' ? 'dark' : 'light'
}

function withTransition(apply: () => void, animate: boolean) {
  const doc = document as Document & { startViewTransition?: (cb: () => void) => unknown }
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches
  if (animate && doc.startViewTransition && !reduced) doc.startViewTransition(apply)
  else apply()
}

const initialMode = readMode()
const initialOpacity = Number.parseFloat(localStorage.getItem(BG_OPACITY_KEY) || '0.15')

export const useThemeStore = create<ThemeStore>((set, get) => ({
  mode: initialMode,
  resolvedTheme: resolve(initialMode),
  bgImage: localStorage.getItem(BG_IMAGE_KEY) || null,
  bgOpacity: Number.isFinite(initialOpacity) ? Math.min(0.4, Math.max(0.05, initialOpacity)) : 0.15,

  setMode: (mode, options = {}) => {
    localStorage.setItem(MODE_KEY, mode)
    const resolved = resolve(mode)
    withTransition(() => {
      applyToDocument(resolved)
      set({ mode, resolvedTheme: resolved })
    }, options.animate ?? false)
  },

  toggle: () => {
    const next: ThemeMode = get().resolvedTheme === 'dark' ? 'warm' : 'dark'
    get().setMode(next, { animate: true })
  },

  setBgImage: url => {
    if (url) localStorage.setItem(BG_IMAGE_KEY, url)
    else localStorage.removeItem(BG_IMAGE_KEY)
    set({ bgImage: url })
  },

  setBgOpacity: v => {
    const clamped = Math.min(0.4, Math.max(0.05, v))
    localStorage.setItem(BG_OPACITY_KEY, String(clamped))
    set({ bgOpacity: clamped })
  },

  resetToDefault: () => {
    localStorage.removeItem(MODE_KEY)
    localStorage.removeItem(BG_IMAGE_KEY)
    localStorage.removeItem(BG_OPACITY_KEY)
    const resolved = resolve('warm')
    applyToDocument(resolved)
    set({ mode: 'warm', resolvedTheme: resolved, bgImage: null, bgOpacity: 0.15 })
  },
}))

// Apply before first paint (imported from main.tsx).
applyToDocument(resolve(initialMode))

window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
  const { mode, setMode } = useThemeStore.getState()
  if (mode === 'system') setMode('system', { animate: true })
})

// Keep tabs in sync.
window.addEventListener('storage', event => {
  if (event.key !== MODE_KEY) return
  const next = readMode()
  const resolved = resolve(next)
  applyToDocument(resolved)
  useThemeStore.setState({ mode: next, resolvedTheme: resolved })
})
