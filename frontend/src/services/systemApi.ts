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

export interface OnboardingStatus {
  has_content: boolean
  demo_seeded: boolean
  auto_show_seen: boolean
  counts: Record<string, number>
  suggested_next_steps: string[]
  stage?: string
  stage_label?: string
  completed_steps?: string[]
}

export interface DemoSeedResult {
  ok: boolean
  already_seeded: boolean
  message: string
  created: Record<string, number>
}

export async function getSystemVersion(): Promise<SystemVersionInfo> {
  return await apiFetch<SystemVersionInfo>('/api/system/version')
}

export async function checkSystemUpdate(): Promise<SystemUpdateInfo> {
  return await apiFetch<SystemUpdateInfo>('/api/system/update-check')
}

export async function getOnboardingStatus(): Promise<OnboardingStatus> {
  return await apiFetch<OnboardingStatus>('/api/system/onboarding-status')
}

export async function dismissOnboarding(): Promise<{ ok: boolean }> {
  return await apiFetch<{ ok: boolean }>('/api/system/onboarding-dismissed', { method: 'POST' })
}

export async function seedDemoWorkspace(): Promise<DemoSeedResult> {
  return await apiFetch<DemoSeedResult>('/api/system/demo-seed', { method: 'POST' })
}
