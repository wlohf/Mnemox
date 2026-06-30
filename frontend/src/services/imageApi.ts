import { apiFetch, withAuthQuery } from './apiClient'

export interface ImageUploadResult {
  url: string
  raw_url: string
  filename: string
  original_name: string
  markdown: string
}

type ImageUploadResponse = Omit<ImageUploadResult, 'raw_url'> & {
  raw_url?: string
}

function withAuthenticatedImageUrl(result: ImageUploadResponse): ImageUploadResult {
  const rawUrl = result.raw_url ?? result.url
  const authedUrl = withAuthQuery(rawUrl)
  return {
    ...result,
    raw_url: rawUrl,
    url: authedUrl,
    markdown: result.markdown.replace(result.url, authedUrl),
  }
}

export async function uploadImageStrict(file: File): Promise<ImageUploadResult> {
  const form = new FormData()
  form.append('file', file)
  const result = await apiFetch<ImageUploadResponse>('/api/images/upload', { method: 'POST', body: form })
  return withAuthenticatedImageUrl(result)
}

export async function uploadBackgroundImageStrict(file: File): Promise<ImageUploadResult> {
  const form = new FormData()
  form.append('file', file)
  const result = await apiFetch<ImageUploadResponse>('/api/images/upload-background', { method: 'POST', body: form })
  return withAuthenticatedImageUrl(result)
}

export async function uploadImage(file: File): Promise<ImageUploadResult | null> {
  try {
    return await uploadImageStrict(file)
  } catch {
    return null
  }
}

export async function uploadImagesBatch(files: File[]): Promise<ImageUploadResult[]> {
  const form = new FormData()
  for (const f of files) form.append('files', f)
  try {
    const results = await apiFetch<ImageUploadResponse[]>('/api/images/upload-batch', { method: 'POST', body: form })
    return results.map(withAuthenticatedImageUrl)
  } catch {
    return []
  }
}
