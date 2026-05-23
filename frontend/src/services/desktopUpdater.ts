import { getDesktopBridge } from './desktopBridge'

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

export interface DesktopUpdateSettings {
  autoCheck: boolean
  intervalMinutes: number
  lastCheckedAt?: number | null
}

export function isDesktopUpdaterAvailable(): boolean {
  const bridge = getDesktopBridge()
  return Boolean(bridge?.checkForUpdates && bridge?.getUpdateState)
}

export async function checkForDesktopUpdate(): Promise<DesktopUpdateState> {
  const bridge = getDesktopBridge()
  if (!bridge?.checkForUpdates) throw new Error('桌面更新器不可用')
  return bridge.checkForUpdates()
}

export async function getDesktopUpdateState(): Promise<DesktopUpdateState> {
  const bridge = getDesktopBridge()
  if (!bridge?.getUpdateState) throw new Error('桌面更新器不可用')
  return bridge.getUpdateState()
}

export async function downloadDesktopUpdate(): Promise<DesktopUpdateState> {
  const bridge = getDesktopBridge()
  if (!bridge?.downloadUpdate) throw new Error('桌面更新器不可用')
  return bridge.downloadUpdate()
}

export async function getDesktopUpdateSettings(): Promise<DesktopUpdateSettings> {
  const bridge = getDesktopBridge()
  if (!bridge?.getUpdateSettings) throw new Error('桌面更新器不可用')
  return bridge.getUpdateSettings()
}

export async function setDesktopUpdateSettings(settings: DesktopUpdateSettings): Promise<DesktopUpdateSettings> {
  const bridge = getDesktopBridge()
  if (!bridge?.setUpdateSettings) throw new Error('桌面更新器不可用')
  return bridge.setUpdateSettings(settings)
}

export async function quitAndInstallDesktopUpdate(): Promise<void> {
  const bridge = getDesktopBridge()
  if (!bridge?.quitAndInstall) throw new Error('桌面更新器不可用')
  return bridge.quitAndInstall()
}

export function subscribeDesktopUpdateState(callback: (state: DesktopUpdateState) => void): (() => void) | null {
  const bridge = getDesktopBridge()
  if (!bridge?.onUpdateState) return null
  return bridge.onUpdateState(callback)
}
