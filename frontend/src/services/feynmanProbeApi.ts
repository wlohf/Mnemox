import { apiFetch } from './apiClient'

export interface FeynmanProbeQuestion {
  type: string
  question: string
  why: string
}

export interface FeynmanProbeResult {
  name: string
  tagline: string
  date: string
  source_excerpt: string
  questions: FeynmanProbeQuestion[]
  strongest_part: string
  next_focus: string
  fallback: boolean
}

export async function generateFeynmanProbe(
  date: string,
  reflection: string,
  maxQuestions = 4,
): Promise<FeynmanProbeResult | null> {
  try {
    return await apiFetch<FeynmanProbeResult>(`/api/plans/${date}/feynman-probe`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ reflection, max_questions: maxQuestions }),
    })
  } catch {
    return null
  }
}
