import type { DesktopUpdateState } from './desktopUpdater'
import type { SystemUpdateInfo } from './systemApi'

const desktopUpdatePhasesWithVersion = new Set<DesktopUpdateState['phase']>([
  'available',
  'downloading',
  'downloaded',
])

export function isDesktopUpdateAvailable(state?: DesktopUpdateState | null): boolean {
  return state?.phase === 'available'
}

export function hasDownloadableUpdate(
  systemInfo?: SystemUpdateInfo | null,
  desktopState?: DesktopUpdateState | null,
): boolean {
  return Boolean(systemInfo?.has_update || isDesktopUpdateAvailable(desktopState))
}

export function hasDirectDownloadUrl(systemInfo?: SystemUpdateInfo | null): boolean {
  return Boolean(systemInfo?.download_url?.trim())
}

export function getUpdateOpenUrl(systemInfo?: SystemUpdateInfo | null): string | null {
  return systemInfo?.download_url?.trim() || systemInfo?.release_page?.trim() || null
}

export function getDisplayedLatestVersion(
  systemInfo?: SystemUpdateInfo | null,
  desktopState?: DesktopUpdateState | null,
): string | null {
  if (
    desktopState?.version &&
    desktopUpdatePhasesWithVersion.has(desktopState.phase)
  ) {
    return desktopState.version
  }
  return systemInfo?.latest_version || null
}

export function getDisplayedReleaseNotes(
  systemInfo?: SystemUpdateInfo | null,
  desktopState?: DesktopUpdateState | null,
): string | null {
  if (
    desktopState?.releaseNotes &&
    desktopUpdatePhasesWithVersion.has(desktopState.phase)
  ) {
    return desktopState.releaseNotes
  }
  return systemInfo?.release_notes || null
}
