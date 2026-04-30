import { apiFetch } from './apiClient'

export interface ObsidianImportResult {
  title: string
  content: string
  images_uploaded: number
  warnings: string[]
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
