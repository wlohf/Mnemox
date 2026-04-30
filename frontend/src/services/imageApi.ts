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
  try {
    return await apiFetch<ImageUploadResult>('/api/images/upload', { method: 'POST', body: form })
  } catch {
    return null
  }
}

export async function uploadImagesBatch(files: File[]): Promise<ImageUploadResult[]> {
  const form = new FormData()
  for (const f of files) form.append('files', f)
  try {
    return await apiFetch<ImageUploadResult[]>('/api/images/upload-batch', { method: 'POST', body: form })
  } catch {
    return []
  }
}
