import { apiFetch, withAuthQuery } from './apiClient'

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
    const result = await apiFetch<ImageUploadResult>('/api/images/upload', { method: 'POST', body: form })
    const authedUrl = withAuthQuery(result.url)
    return {
      ...result,
      url: authedUrl,
      markdown: result.markdown.replace(result.url, authedUrl),
    }
  } catch {
    return null
  }
}

export async function uploadImagesBatch(files: File[]): Promise<ImageUploadResult[]> {
  const form = new FormData()
  for (const f of files) form.append('files', f)
  try {
    const results = await apiFetch<ImageUploadResult[]>('/api/images/upload-batch', { method: 'POST', body: form })
    return results.map((result) => {
      const authedUrl = withAuthQuery(result.url)
      return {
        ...result,
        url: authedUrl,
        markdown: result.markdown.replace(result.url, authedUrl),
      }
    })
  } catch {
    return []
  }
}
