export interface DesktopUpdateState {
  phase: 'idle' | 'checking' | 'available' | 'not-available' | 'downloading' | 'downloaded' | 'error'
  version?: string | null
  currentVersion?: string | null
  releaseNotes?: string | null
  releaseDate?: string | null
  progressPercent?: number
  bytesPerSecond?: number
  transferred?: number
  total?: number
  message?: string
  error?: string | null
}

interface DesktopUpdaterBridge {
  checkForUpdates: () => Promise<DesktopUpdateState>
  getUpdateState: () => Promise<DesktopUpdateState>
  getUpdateSettings: () => Promise<DesktopUpdateSettings>
  setUpdateSettings: (settings: DesktopUpdateSettings) => Promise<DesktopUpdateSettings>
  downloadUpdate: () => Promise<DesktopUpdateState>
  quitAndInstall: () => Promise<void>
  onUpdateState: (callback: (state: DesktopUpdateState) => void) => () => void
}

export interface DesktopUpdateSettings {
  autoCheck: boolean
  intervalMinutes: number
  lastCheckedAt?: number | null
}

declare global {
  interface Window {
    mnemoxDesktop?: DesktopUpdaterBridge
  }
}

function getBridge(): DesktopUpdaterBridge | null {
  return window.mnemoxDesktop ?? null
}

export function isDesktopUpdaterAvailable(): boolean {
  return Boolean(getBridge())
}

export async function checkForDesktopUpdate(): Promise<DesktopUpdateState> {
  const bridge = getBridge()
  if (!bridge) throw new Error('桌面更新器不可用')
  return bridge.checkForUpdates()
}

export async function getDesktopUpdateState(): Promise<DesktopUpdateState> {
  const bridge = getBridge()
  if (!bridge) throw new Error('桌面更新器不可用')
  return bridge.getUpdateState()
}

export async function downloadDesktopUpdate(): Promise<DesktopUpdateState> {
  const bridge = getBridge()
  if (!bridge) throw new Error('桌面更新器不可用')
  return bridge.downloadUpdate()
}

export async function getDesktopUpdateSettings(): Promise<DesktopUpdateSettings> {
  const bridge = getBridge()
  if (!bridge) throw new Error('桌面更新器不可用')
  return bridge.getUpdateSettings()
}

export async function setDesktopUpdateSettings(settings: DesktopUpdateSettings): Promise<DesktopUpdateSettings> {
  const bridge = getBridge()
  if (!bridge) throw new Error('桌面更新器不可用')
  return bridge.setUpdateSettings(settings)
}

export async function quitAndInstallDesktopUpdate(): Promise<void> {
  const bridge = getBridge()
  if (!bridge) throw new Error('桌面更新器不可用')
  return bridge.quitAndInstall()
}

export function subscribeDesktopUpdateState(callback: (state: DesktopUpdateState) => void): (() => void) | null {
  const bridge = getBridge()
  if (!bridge) return null
  return bridge.onUpdateState(callback)
}
