import { apiFetch } from './apiClient'

export interface AnkiCardItem {
  id: number
  front: string
  back: string
  source: 'manual' | 'ai' | string
  tags?: string | null
  note?: string | null
  due_at?: string | null
  interval_days: number
  ease_factor: number
  repetitions: number
  last_quality?: number | null
  created_at?: string | null
}

export interface AnkiQueueResponse {
  new_cards: AnkiCardItem[]
  review_cards: AnkiCardItem[]
}

export async function listAnkiCards(scope: 'due' | 'all' = 'due', limit = 50): Promise<AnkiCardItem[]> {
  try {
    return await apiFetch<AnkiCardItem[]>(`/api/anki/cards?scope=${scope}&limit=${limit}`)
  } catch {
    return []
  }
}

export async function createAnkiCard(data: {
  front: string
  back: string
  tags?: string
  note?: string
}): Promise<AnkiCardItem | null> {
  try {
    return await apiFetch<AnkiCardItem>('/api/anki/cards', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    })
  } catch {
    return null
  }
}

export async function reviewAnkiCard(cardId: number, quality: number): Promise<AnkiCardItem | null> {
  try {
    return await apiFetch<AnkiCardItem>(`/api/anki/cards/${cardId}/review`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ quality }),
    })
  } catch {
    return null
  }
}

export async function aiGenerateAnkiCards(data: {
  topic: string
  source_text?: string
  count?: number
  tags?: string
}): Promise<{ created: number; cards: AnkiCardItem[] } | null> {
  try {
    return await apiFetch<{ created: number; cards: AnkiCardItem[] }>('/api/anki/cards/ai-generate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    })
  } catch {
    return null
  }
}

export async function getAnkiQueue(newLimit = 20, reviewLimit = 100): Promise<AnkiQueueResponse | null> {
  try {
    return await apiFetch<AnkiQueueResponse>(`/api/anki/queue?new_limit=${newLimit}&review_limit=${reviewLimit}`)
  } catch {
    return null
  }
}

export async function exportAnkiCardsCSV(): Promise<{ filename: string; csv: string; count: number } | null> {
  try {
    return await apiFetch<{ filename: string; csv: string; count: number }>('/api/anki/cards/export')
  } catch {
    return null
  }
}

export async function importAnkiCardsCSV(csvText: string): Promise<{ created: number; skipped: number } | null> {
  try {
    return await apiFetch<{ created: number; skipped: number }>('/api/anki/cards/import', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ csv_text: csvText }),
    })
  } catch {
    return null
  }
}
