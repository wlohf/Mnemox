import { apiFetch } from './apiClient'

export interface ImageUploadResult {
  url: string
  filename: string
  original_name: string
  markdown: string
}

export async function uploadImage(file: File): Promise<ImageUploadResult | null> {
  const form = new FormData()
  form.append('file', file)
  const res = await apiFetch('/api/images/upload', { method: 'POST', body: form })
  if (!res.ok) return null
  return res.json()
}

export async function uploadImagesBatch(files: File[]): Promise<ImageUploadResult[]> {
  const form = new FormData()
  for (const f of files) form.append('files', f)
  const res = await apiFetch('/api/images/upload-batch', { method: 'POST', body: form })
  if (!res.ok) return []
  return res.json()
}
