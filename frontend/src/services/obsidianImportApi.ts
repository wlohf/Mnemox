import { apiFetch } from './apiClient'

export interface ObsidianImportResult {
  title: string
  content: string
  images_uploaded: number
  warnings: string[]
}

export interface ObsidianVaultConflict {
  note_id: number
  title: string
  source_path: string
}

export interface ObsidianVaultFailure {
  source_path: string
  reason: string
}

export interface ObsidianVaultSyncResult {
  scanned: number
  created: number
  updated: number
  skipped: number
  failed: number
  truncated: boolean
  renamed: number
  missing: number
  conflicted: number
  conflicts: ObsidianVaultConflict[]
  failures: ObsidianVaultFailure[]
}

export interface ObsidianVaultConflictResolution {
  ok: boolean
  note_id: number
  strategy: 'keep_local' | 'use_vault'
  title: string
  source_path: string
}

export async function importObsidianNote(
  mdFile: File,
  attachments: File[],
  title?: string,
): Promise<ObsidianImportResult | null> {
  const form = new FormData()
  form.append('md_file', mdFile)
  for (const a of attachments) form.append('attachments', a)
  if (title) form.append('title', title)
  try {
    return await apiFetch<ObsidianImportResult>('/api/obsidian/import', { method: 'POST', body: form })
  } catch {
    return null
  }
}

export async function syncObsidianVault(vaultPath: string): Promise<ObsidianVaultSyncResult | null> {
  try {
    return await apiFetch<ObsidianVaultSyncResult>('/api/obsidian/sync-vault', {
      method: 'POST',
      body: JSON.stringify({ vault_path: vaultPath }),
    })
  } catch {
    return null
  }
}

export async function resolveObsidianVaultConflict(
  noteId: number,
  strategy: 'keep_local' | 'use_vault',
): Promise<ObsidianVaultConflictResolution | null> {
  try {
    return await apiFetch<ObsidianVaultConflictResolution>(
      `/api/obsidian/sync-vault/conflicts/${noteId}/resolve`,
      {
        method: 'POST',
        body: JSON.stringify({ strategy }),
      },
    )
  } catch {
    return null
  }
}
