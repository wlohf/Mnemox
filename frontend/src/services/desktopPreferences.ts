import { getDesktopBridge } from './desktopBridge'

export function isDesktopPreferencesAvailable(): boolean {
  const bridge = getDesktopBridge()
  return Boolean(bridge?.getPreference && bridge?.setPreference)
}

export async function getDesktopPreference<T>(key: string): Promise<T | null> {
  const bridge = getDesktopBridge()
  if (!bridge?.getPreference) return null
  try {
    return await bridge.getPreference<T>(key)
  } catch {
    return null
  }
}

export async function setDesktopPreference<T>(key: string, value: T): Promise<boolean> {
  const bridge = getDesktopBridge()
  if (!bridge?.setPreference) return false
  try {
    await bridge.setPreference(key, value)
    return true
  } catch {
    return false
  }
}
