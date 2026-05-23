import { getDesktopBridge, type SavedLogin } from './desktopBridge'

export type { SavedLogin }

function normalizeSavedLogin(value: SavedLogin | null | undefined): SavedLogin | null {
  if (!value?.username?.trim() || !value.password) return null
  return {
    username: value.username.trim(),
    password: value.password,
    autoLogin: value.autoLogin === true,
  }
}

export function isDesktopAuthAvailable(): boolean {
  const bridge = getDesktopBridge()
  return Boolean(bridge?.getSavedLogin && bridge?.saveLogin && bridge?.clearSavedLogin)
}

export async function getSavedLogin(): Promise<SavedLogin | null> {
  const bridge = getDesktopBridge()
  if (!bridge?.getSavedLogin) return null
  try {
    return normalizeSavedLogin(await bridge.getSavedLogin())
  } catch {
    return null
  }
}

export async function saveLoginIfAvailable(payload: SavedLogin): Promise<boolean> {
  const bridge = getDesktopBridge()
  if (!bridge?.saveLogin) return false
  await bridge.saveLogin({
    username: payload.username.trim(),
    password: payload.password,
    autoLogin: payload.autoLogin === true,
  })
  return true
}

export async function clearSavedLogin(): Promise<boolean> {
  const bridge = getDesktopBridge()
  if (!bridge?.clearSavedLogin) return false
  await bridge.clearSavedLogin()
  return true
}
