import { getToken } from './apiClient'

export interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
  image_data?: string[]
}

export interface DetectedMaterial {
  id: number
  title: string
}

export interface MemoryIndicator {
  id: number
  category: string
  value: string
  memory_type?: string
}

export interface ProgressFeedback {
  feedback_type: 'understanding' | 'persistence' | 'correction_accepted' | 'milestone'
  message: string
  emoji: string
}

export interface WebSearchResult {
  title: string
  url: string
  snippet?: string
}

/**
 * 通过 SSE 流式发送消息，逐块回调 AI 回复内容
 */
export async function sendMessageStream(
  message: string,
  history: ChatMessage[],
  onChunk: (chunk: string) => void,
  onDone: () => void,
  onError: (error: string) => void,
  materialIds?: number[],
  onMaterialsDetected?: (materials: DetectedMaterial[]) => void,
  signal?: AbortSignal,
  conversationId?: number,
  imageData?: string[],
  studySessionId?: number,
  chatMode?: string,
  onMemoryIndicators?: (memories: MemoryIndicator[]) => void,
  onProgressFeedback?: (feedback: ProgressFeedback) => void,
  providerName?: string,
  model?: string,
  webSearchEnabled?: boolean,
  onWebSearchResults?: (results: WebSearchResult[]) => void,
  onWebSearchNotice?: (notice: string) => void,
): Promise<void> {
  try {
    const payload: any = {
      message,
      history: history.map(m => ({ role: m.role, content: m.content })),
    }
    if (materialIds && materialIds.length > 0) {
      payload.material_ids = materialIds
    }
    if (conversationId) {
      payload.conversation_id = conversationId
    }
    if (imageData && imageData.length > 0) {
      payload.image_data = imageData
    }
    if (studySessionId) {
      payload.study_session_id = studySessionId
    }
    if (chatMode && chatMode !== 'normal') {
      payload.chat_mode = chatMode
    }
    if (providerName) {
      payload.provider_name = providerName
    }
    if (model) {
      payload.model = model
    }
    if (webSearchEnabled) {
      payload.web_search_enabled = true
    }
    const token = getToken()
    const res = await fetch('/api/chat/send', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify(payload),
      signal,
    })

    if (!res.ok) {
      const err = await res.json().catch(() => null)
      const detail = err?.detail
      onError(typeof detail === 'string' ? detail : detail?.message || `请求失败 (${res.status})`)
      return
    }

    const reader = res.body?.getReader()
    if (!reader) {
      onError('浏览器不支持流式读取')
      return
    }

    const decoder = new TextDecoder()
    let buffer = ''

    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      // 保留最后一个可能不完整的行
      buffer = lines.pop() || ''

      for (const line of lines) {
        const trimmed = line.trim()
        if (!trimmed || !trimmed.startsWith('data: ')) continue

        const data = trimmed.slice(6)
        if (data === '[DONE]') {
          onDone()
          return
        }

        try {
          const parsed = JSON.parse(data)
          if (parsed.type === 'materials_detected' && parsed.materials) {
            onMaterialsDetected?.(parsed.materials as DetectedMaterial[])
            continue
          }
          if (parsed.type === 'memory_indicators' && parsed.memories) {
            onMemoryIndicators?.(parsed.memories as MemoryIndicator[])
            continue
          }
          if (parsed.type === 'progress_feedback' && parsed.feedback) {
            onProgressFeedback?.(parsed.feedback as ProgressFeedback)
            continue
          }
          if (parsed.type === 'web_search_results') {
            onWebSearchResults?.((parsed.results || []) as WebSearchResult[])
            continue
          }
          if (parsed.type === 'web_search_notice' && parsed.message) {
            onWebSearchNotice?.(String(parsed.message))
            continue
          }
          if (parsed.error) {
            onError(parsed.error)
            return
          }
          if (parsed.content) {
            onChunk(parsed.content)
          }
        } catch {
          // 忽略解析失败的行
        }
      }
    }

    onDone()
  } catch (e: any) {
    if (e?.name === 'AbortError') {
      // User stopped streaming — treat as done, not error
      onDone()
      return
    }
    onError(e?.message || '网络错误，请检查后端是否启动')
  }
}
