import { describe, expect, it } from 'vitest'
import type { DesktopUpdateState } from './desktopUpdater'
import type { SystemUpdateInfo } from './systemApi'
import {
  getDisplayedLatestVersion,
  getDisplayedReleaseNotes,
  getUpdateOpenUrl,
  hasDownloadableUpdate,
  hasDirectDownloadUrl,
  isDesktopUpdateAvailable,
} from './updateDisplay'

const systemNoUpdate: SystemUpdateInfo = {
  has_update: false,
  current_version: '1.0.0',
  latest_version: '1.0.0',
  release_notes: '未配置更新源（APP_UPDATE_MANIFEST_URL）',
  checked_at: '2026-05-23T00:00:00Z',
}

describe('update display helpers', () => {
  it('uses desktop updater availability even when the system manifest has no update', () => {
    const desktopState: DesktopUpdateState = {
      phase: 'available',
      version: '1.0.3',
      releaseNotes: 'Desktop release notes',
    }

    expect(isDesktopUpdateAvailable(desktopState)).toBe(true)
    expect(hasDownloadableUpdate(systemNoUpdate, desktopState)).toBe(true)
    expect(getDisplayedLatestVersion(systemNoUpdate, desktopState)).toBe('1.0.3')
    expect(getDisplayedReleaseNotes(systemNoUpdate, desktopState)).toBe('Desktop release notes')
  })

  it('falls back to the system manifest when desktop updater has no available update', () => {
    const systemInfo: SystemUpdateInfo = {
      has_update: true,
      current_version: '1.0.2',
      latest_version: '1.0.3',
      release_notes: 'Manifest release notes',
      checked_at: '2026-05-23T00:00:00Z',
    }

    expect(hasDownloadableUpdate(systemInfo, { phase: 'not-available', version: '1.0.2' })).toBe(true)
    expect(getDisplayedLatestVersion(systemInfo, { phase: 'not-available', version: '1.0.2' })).toBe('1.0.3')
    expect(getDisplayedReleaseNotes(systemInfo, { phase: 'not-available', releaseNotes: 'ignored' })).toBe('Manifest release notes')
  })

  it('opens release page when no installer asset URL is published', () => {
    const systemInfo: SystemUpdateInfo = {
      has_update: true,
      current_version: '1.0.6',
      latest_version: '1.0.7',
      release_notes: 'Release metadata only',
      release_page: 'https://github.com/wlohf/Mnemox/releases/tag/v1.0.7',
      checked_at: '2026-06-06T00:00:00Z',
    }

    expect(hasDirectDownloadUrl(systemInfo)).toBe(false)
    expect(getUpdateOpenUrl(systemInfo)).toBe('https://github.com/wlohf/Mnemox/releases/tag/v1.0.7')
  })

  it('prefers direct installer URL when present', () => {
    const systemInfo: SystemUpdateInfo = {
      has_update: true,
      current_version: '1.0.6',
      latest_version: '1.0.7',
      release_page: 'https://github.com/wlohf/Mnemox/releases/tag/v1.0.7',
      download_url: 'https://github.com/wlohf/Mnemox/releases/download/v1.0.7/Mnemox-Setup-1.0.7.exe',
      checked_at: '2026-06-06T00:00:00Z',
    }

    expect(hasDirectDownloadUrl(systemInfo)).toBe(true)
    expect(getUpdateOpenUrl(systemInfo)).toBe(systemInfo.download_url)
  })
})
