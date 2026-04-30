import { apiFetch } from './apiClient'

export interface SystemVersionInfo {
  app_name: string
  current_version: string
  checked_at: string
}

export interface SystemUpdateInfo {
  has_update: boolean
  current_version: string
  latest_version?: string | null
  release_notes?: string | null
  release_page?: string | null
  download_url?: string | null
  published_at?: string | null
  checked_at: string
}

export async function getSystemVersion(): Promise<SystemVersionInfo | null> {
  try {
    return await apiFetch<SystemVersionInfo>('/api/system/version')
  } catch {
    return null
  }
}

export async function checkSystemUpdate(): Promise<SystemUpdateInfo | null> {
  try {
    return await apiFetch<SystemUpdateInfo>('/api/system/update-check')
  } catch {
    return null
  }
}
