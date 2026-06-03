import type { DesktopUpdateSettings, DesktopUpdateState } from './desktopUpdater'

export interface SavedLogin {
  username: string
  password: string
  autoLogin: boolean
}

export interface PomodoroReminderPayload {
  taskName: string
  dueAt: number
  mode: 'focus' | 'break'
}

export interface MnemoxDesktopBridge {
  checkForUpdates?: () => Promise<DesktopUpdateState>
  getUpdateState?: () => Promise<DesktopUpdateState>
  getUpdateSettings?: () => Promise<DesktopUpdateSettings>
  setUpdateSettings?: (settings: DesktopUpdateSettings) => Promise<DesktopUpdateSettings>
  downloadUpdate?: () => Promise<DesktopUpdateState>
  quitAndInstall?: () => Promise<void>
  onUpdateState?: (callback: (state: DesktopUpdateState) => void) => () => void
  getSavedLogin?: () => Promise<SavedLogin | null>
  saveLogin?: (payload: SavedLogin) => Promise<void>
  clearSavedLogin?: () => Promise<void>
  getPreference?: <T = unknown>(key: string) => Promise<T | null>
  setPreference?: <T = unknown>(key: string, value: T) => Promise<T | null>
  setPomodoroReminder?: (payload: PomodoroReminderPayload) => Promise<void>
  clearPomodoroReminder?: () => Promise<void>
  onReminderTriggered?: (callback: (payload: PomodoroReminderPayload) => void) => () => void
}

declare global {
  interface Window {
    mnemoxDesktop?: MnemoxDesktopBridge
  }
}

export function getDesktopBridge(): MnemoxDesktopBridge | null {
  return window.mnemoxDesktop ?? null
}
