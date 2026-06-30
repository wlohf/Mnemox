import { describe, expect, it, vi } from 'vitest'

describe('desktop updater bridge', () => {
  it('returns null when desktop bridge is unavailable', async () => {
    const mod = await import('./desktopUpdater')
    expect(mod.isDesktopUpdaterAvailable()).toBe(false)
    await expect(mod.checkForDesktopUpdate()).rejects.toThrow(/桌面更新/)
  })

  it('uses desktop bridge when present', async () => {
    const checkForUpdates = vi.fn().mockResolvedValue({ phase: 'checking' })
    const getUpdateState = vi.fn().mockResolvedValue({ phase: 'idle' })
    const getUpdateSettings = vi.fn().mockResolvedValue({ autoCheck: true, intervalMinutes: 360, lastCheckedAt: null })
    const setUpdateSettings = vi.fn().mockResolvedValue({ autoCheck: false, intervalMinutes: 30, lastCheckedAt: null })
    const onUpdateState = vi.fn().mockReturnValue(() => {})
    const downloadUpdate = vi.fn().mockResolvedValue({ phase: 'downloading' })
    const downloadInstallerAndRun = vi.fn().mockResolvedValue({ phase: 'downloading' })
    const quitAndInstall = vi.fn().mockResolvedValue(undefined)

    ;(window as Window & { mnemoxDesktop?: unknown }).mnemoxDesktop = {
      checkForUpdates,
      getUpdateState,
      getUpdateSettings,
      setUpdateSettings,
      onUpdateState,
      downloadUpdate,
      downloadInstallerAndRun,
      quitAndInstall,
    }

    const mod = await import('./desktopUpdater')

    expect(mod.isDesktopUpdaterAvailable()).toBe(true)
    expect(await mod.checkForDesktopUpdate()).toEqual({ phase: 'checking' })
    expect(await mod.getDesktopUpdateState()).toEqual({ phase: 'idle' })
    expect(await mod.getDesktopUpdateSettings()).toEqual({ autoCheck: true, intervalMinutes: 360, lastCheckedAt: null })
    expect(await mod.setDesktopUpdateSettings({ autoCheck: false, intervalMinutes: 30 })).toEqual({ autoCheck: false, intervalMinutes: 30, lastCheckedAt: null })
    expect(await mod.downloadDesktopUpdate()).toEqual({ phase: 'downloading' })
    expect(await mod.downloadInstallerAndRunDesktopUpdate({ url: 'https://example.test/mnemox.exe', version: '1.1.1' })).toEqual({ phase: 'downloading' })
    const unsubscribe = mod.subscribeDesktopUpdateState(() => {})
    expect(typeof unsubscribe).toBe('function')
    expect(onUpdateState).toHaveBeenCalled()
    await expect(mod.quitAndInstallDesktopUpdate()).resolves.toBeUndefined()
  })
})
