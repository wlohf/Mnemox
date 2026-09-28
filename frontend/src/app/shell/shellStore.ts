import { create } from 'zustand'
import { useLayoutEffect, type ReactNode } from 'react'

/*
 * Shell UI state: sidebar collapse, the right-hand context panel (evidence /
 * page-specific aside), immersive mode, command palette, and dialogs that any
 * screen may open (settings, onboarding, sync conflicts).
 */

const SIDEBAR_KEY = 'mx_sidebar_collapsed'
const IMMERSIVE_KEY = 'mx_immersive'

export type SettingsSection = 'appearance' | 'ai' | 'coach' | 'prompts' | 'motivation' | 'system' | 'account'

interface ShellState {
  sidebarCollapsed: boolean
  mobileNavOpen: boolean
  asideOpen: boolean
  immersive: boolean
  commandOpen: boolean
  settingsOpen: boolean
  settingsSection: SettingsSection
  settingsArg: string | null
  onboardingOpen: boolean
  conflictsOpen: boolean
  toggleSidebar: () => void
  setSidebarCollapsed: (v: boolean) => void
  setMobileNav: (v: boolean) => void
  setAsideOpen: (v: boolean) => void
  toggleAside: () => void
  setImmersive: (v: boolean) => void
  setCommandOpen: (v: boolean) => void
  openSettings: (section?: SettingsSection, arg?: string | null) => void
  closeSettings: () => void
  setOnboardingOpen: (v: boolean) => void
  setConflictsOpen: (v: boolean) => void
}

const readBool = (key: string) => {
  try {
    return localStorage.getItem(key) === 'true'
  } catch {
    return false
  }
}
const writeBool = (key: string, v: boolean) => {
  try {
    localStorage.setItem(key, String(v))
  } catch {
    /* storage may be unavailable */
  }
}

export const useShell = create<ShellState>(set => ({
  sidebarCollapsed: readBool(SIDEBAR_KEY),
  mobileNavOpen: false,
  asideOpen: false,
  immersive: readBool(IMMERSIVE_KEY),
  commandOpen: false,
  settingsOpen: false,
  settingsSection: 'appearance',
  settingsArg: null,
  onboardingOpen: false,
  conflictsOpen: false,
  toggleSidebar: () =>
    set(s => {
      writeBool(SIDEBAR_KEY, !s.sidebarCollapsed)
      return { sidebarCollapsed: !s.sidebarCollapsed }
    }),
  setSidebarCollapsed: v => {
    writeBool(SIDEBAR_KEY, v)
    set({ sidebarCollapsed: v })
  },
  setMobileNav: v => set({ mobileNavOpen: v }),
  setAsideOpen: v => set({ asideOpen: v }),
  toggleAside: () => set(s => ({ asideOpen: !s.asideOpen })),
  setImmersive: v => {
    writeBool(IMMERSIVE_KEY, v)
    set({ immersive: v })
  },
  setCommandOpen: v => set({ commandOpen: v }),
  openSettings: (section, arg = null) => set({ settingsOpen: true, settingsSection: section ?? 'appearance', settingsArg: arg }),
  closeSettings: () => set({ settingsOpen: false }),
  setOnboardingOpen: v => set({ onboardingOpen: v }),
  setConflictsOpen: v => set({ conflictsOpen: v }),
}))

/* ---------------------------------------------------------------------------
   Page chrome slots: a page declares its title, top-bar actions and aside
   panel; the shell renders them. Stored outside React tree state so updating
   the chrome re-renders only the top bar / aside, never the page itself.
--------------------------------------------------------------------------- */

export interface PageChrome {
  title?: ReactNode
  actions?: ReactNode
  aside?: ReactNode
  asideLabel?: string
  /** Page manages its own scrolling (chat, editors). */
  bare?: boolean
}

export const useChrome = create<PageChrome>(() => ({}))

/** Register page chrome for the lifetime of the calling page. */
export function usePageChrome(chrome: PageChrome) {
  useLayoutEffect(() => {
    useChrome.setState(chrome, true)
  })
  useLayoutEffect(() => () => useChrome.setState({}, true), [])
}
