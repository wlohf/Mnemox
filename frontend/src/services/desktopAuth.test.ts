import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
  clearSavedLogin,
  getSavedLogin,
  isDesktopAuthAvailable,
  saveLoginIfAvailable,
} from './desktopAuth'

describe('desktopAuth bridge wrapper', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    delete window.mnemoxDesktop
  })

  it('safely no-ops outside Electron', async () => {
    expect(isDesktopAuthAvailable()).toBe(false)
    expect(await getSavedLogin()).toBeNull()
    await expect(saveLoginIfAvailable({ username: 'u', password: 'p', autoLogin: true })).resolves.toBe(false)
    await expect(clearSavedLogin()).resolves.toBe(false)
  })

  it('delegates saved login operations to the desktop bridge', async () => {
    window.mnemoxDesktop = {
      getSavedLogin: vi.fn().mockResolvedValue({ username: 'u', password: 'p', autoLogin: true }),
      saveLogin: vi.fn().mockResolvedValue(undefined),
      clearSavedLogin: vi.fn().mockResolvedValue(undefined),
    } as any

    await expect(getSavedLogin()).resolves.toEqual({ username: 'u', password: 'p', autoLogin: true })
    await expect(saveLoginIfAvailable({ username: 'u', password: 'p', autoLogin: false })).resolves.toBe(true)
    await expect(clearSavedLogin()).resolves.toBe(true)

    expect(window.mnemoxDesktop!.saveLogin).toHaveBeenCalledWith({
      username: 'u',
      password: 'p',
      autoLogin: false,
    })
  })
})
