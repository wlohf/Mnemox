import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { toast } from '../../ui'
import {
  sendMessageStream,
  type ChatMessage,
  type DetectedMaterial,
  type MemoryIndicator,
  type NoteContextIndicator,
  type WebSearchResult,
} from '../../services/chatApi'
import {
  appendConversationMessages,
  createConversation,
  forkConversation,
  getConversation,
} from '../../services/conversationApi'
import { getConversationPath } from '../../services/conversationRoute'
import { draftAgentWrite, executeAgentWrite, type AgentWriteDraftResponse } from '../../services/agentApi'
import { detectCoachChatEvent, evaluateCoach } from '../../services/coachApi'
import { getStoredWebSearchMode, getStoredWebSearchProviderName } from '../../services/aiSettingsApi'
import { syncEngine } from '../../sync/SyncEngine'
import { qk } from '../../app/queryClient'

/*
 * Chat controller: one conversation's messages, streaming, branching and the
 * "draft before write" agent flow. Keeps the legacy behaviour contract.
 */

export interface TurnContext {
  memories: MemoryIndicator[]
  notes: NoteContextIndicator[]
  web: WebSearchResult[]
  materials: DetectedMaterial[]
  notice?: string
}

const EMPTY_CTX: TurnContext = { memories: [], notes: [], web: [], materials: [] }

const WRITE_TRIGGERS = [
  '记个笔记', '记一条笔记', '记一个笔记', '记个灵感', '记一个灵感', '记录一下', '写入笔记', '存到笔记', '保存到笔记', '记到笔记', '记进笔记', '突然有个想法', '临时有个想法', '有个想法', '有一个想法', '我想到',
  '今天的任务', '今天任务', '今日任务', '今天的计划', '今天计划', '今日计划', '今天待办', '今日待办', '加入今天计划', '加到今天计划', '写到今天计划', '安排到今天',
  '创建任务', '添加任务', '加入任务', '安排任务', '制定任务', '拆成任务', '拆成子任务', '拆解任务', '生成任务', '做成任务', '目标是', '我的目标', '接下来我要', '接下来我的目标',
]
export const shouldCheckAgentWrite = (text: string) => WRITE_TRIGGERS.some(t => text.includes(t))

function studySessionId(): number | undefined {
  try {
    const raw = localStorage.getItem('study_active_session_id')
    return raw ? Number(raw) : undefined
  } catch {
    return undefined
  }
}

export interface SendOptions {
  images?: string[]
  materialIds?: number[]
  providerName?: string
  model?: string
  webSearch?: boolean
  projectId?: number | null
}

export function useChatController(conversationId: number | null) {
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [loadingConversation, setLoadingConversation] = useState(false)
  const [streaming, setStreaming] = useState('')
  const [busy, setBusy] = useState(false)
  const [turn, setTurn] = useState<TurnContext>(EMPTY_CTX)
  const [writeDraft, setWriteDraft] = useState<AgentWriteDraftResponse | null>(null)
  const [writeSource, setWriteSource] = useState('')
  const [writeBusy, setWriteBusy] = useState(false)
  const abortRef = useRef<AbortController | null>(null)
  const convRef = useRef<number | null>(conversationId)
  const messagesRef = useRef<ChatMessage[]>([])
  messagesRef.current = messages

  // Load the routed conversation.
  useEffect(() => {
    convRef.current = conversationId
    if (conversationId === null) {
      setMessages([])
      setTurn(EMPTY_CTX)
      return
    }
    let cancelled = false
    setLoadingConversation(true)
    getConversation(conversationId)
      .then(detail => {
        if (cancelled) return
        setMessages(detail.messages.map(m => ({ role: m.role, content: m.content, image_data: m.image_data || undefined })))
        try {
          localStorage.setItem('chat_activeConversationId', String(conversationId))
        } catch {
          /* ignore */
        }
      })
      .catch(err => {
        if (cancelled) return
        toast.error(err instanceof Error ? err.message : '加载历史对话失败')
        navigate('/', { replace: true })
      })
      .finally(() => !cancelled && setLoadingConversation(false))
    return () => {
      cancelled = true
    }
  }, [conversationId, navigate])

  const refreshLists = useCallback(() => {
    void qc.invalidateQueries({ queryKey: ['conversations'] })
    void qc.invalidateQueries({ queryKey: qk.reviewDue })
  }, [qc])

  const ensureConversation = useCallback(async (projectId?: number | null): Promise<number> => {
    if (convRef.current) return convRef.current
    const conv = await createConversation({ title: '新对话', project_id: projectId ?? undefined })
    convRef.current = conv.id
    navigate(getConversationPath(conv.id), { replace: true })
    void qc.invalidateQueries({ queryKey: ['conversations'] })
    return conv.id
  }, [navigate, qc])

  const stream = useCallback(async (
    text: string,
    opts: SendOptions & { history?: ChatMessage[]; replace?: ChatMessage[]; conversationId?: number } = {},
  ) => {
    const convId = opts.conversationId ?? (await ensureConversation(opts.projectId))
    const user: ChatMessage = { role: 'user', content: text, image_data: opts.images?.length ? opts.images : undefined }
    const history = opts.history ?? messagesRef.current
    setMessages(opts.replace ? [...opts.replace, user] : [...messagesRef.current, user])
    setBusy(true)
    setStreaming('')
    setTurn(EMPTY_CTX)
    let acc = ''
    const controller = new AbortController()
    abortRef.current = controller

    const coachEvent = !opts.replace ? detectCoachChatEvent(text) : null
    if (coachEvent) {
      void evaluateCoach({
        event: {
          event_type: coachEvent,
          source: 'chat',
          payload: { text, conversation_id: convId },
          severity: coachEvent === 'chat.frustration_detected' ? 'warning' : 'info',
          dedupe_key: `${coachEvent}:${convId}:${text.slice(0, 80)}`,
        },
        include_memories: true,
      }).then(() => qc.invalidateQueries({ queryKey: qk.coachNudges }))
    }

    await sendMessageStream(
      text,
      history,
      chunk => {
        acc += chunk
        setStreaming(acc)
      },
      () => {
        if (acc) setMessages(prev => [...prev, { role: 'assistant', content: acc }])
        setStreaming('')
        setBusy(false)
        abortRef.current = null
        refreshLists()
      },
      error => {
        toast.error('回答没有生成', { description: error })
        setStreaming('')
        setBusy(false)
        abortRef.current = null
      },
      opts.materialIds,
      materials => setTurn(t => ({ ...t, materials })),
      controller.signal,
      convId,
      opts.images?.length ? opts.images : undefined,
      studySessionId(),
      'normal',
      memories => setTurn(t => ({ ...t, memories })),
      notes => setTurn(t => ({ ...t, notes })),
      feedback =>
        toast.evidence(`${feedback.emoji} 进度提醒`, {
          description: feedback.message,
          actions: [{ label: '查看', onClick: () => navigate('/progress') }],
        }),
      opts.providerName,
      opts.model,
      opts.webSearch ?? true,
      getStoredWebSearchMode(),
      getStoredWebSearchProviderName(),
      web => setTurn(t => ({ ...t, web })),
      notice => setTurn(t => ({ ...t, notice })),
    )
  }, [ensureConversation, navigate, qc, refreshLists])

  /** Entry point for the composer: may route through the agent write draft. */
  const send = useCallback(async (text: string, opts: SendOptions = {}): Promise<boolean> => {
    const clean = text.trim()
    if (!clean || busy || writeBusy) return false
    if (!opts.images?.length && shouldCheckAgentWrite(clean)) {
      setWriteBusy(true)
      try {
        const draft = await draftAgentWrite(clean)
        if (draft.requires_confirmation && draft.intent !== 'none') {
          setWriteDraft(draft)
          setWriteSource(clean)
          return true
        }
      } catch (err) {
        toast.error(err instanceof Error ? err.message : '草案生成失败，已按普通提问处理')
      } finally {
        setWriteBusy(false)
      }
    }
    void stream(clean, opts)
    return true
  }, [busy, stream, writeBusy])

  const stop = useCallback(() => abortRef.current?.abort(), [])

  const fork = useCallback(async (upToIndex: number, title: string) => {
    const id = convRef.current
    if (!id) {
      toast.warning('先发送一轮消息，再从这里创建分支')
      return null
    }
    const f = await forkConversation(id, { title, up_to_index: upToIndex })
    convRef.current = f.id
    navigate(getConversationPath(f.id))
    void qc.invalidateQueries({ queryKey: ['conversations'] })
    return f
  }, [navigate, qc])

  const branchAt = useCallback(async (index: number) => {
    const f = await fork(index, '对话分支')
    if (f) toast.success('已创建对话分支', { description: '新的分支从这条回答之后继续。' })
  }, [fork])

  const regenerate = useCallback(async (assistantIndex: number) => {
    if (busy) return
    const list = messagesRef.current
    let userIndex = -1
    for (let i = assistantIndex - 1; i >= 0; i--) if (list[i].role === 'user') { userIndex = i; break }
    if (userIndex < 0) return
    const prefix = list.slice(0, userIndex)
    const f = await fork(userIndex - 1, '重新生成')
    if (!f) return
    await stream(list[userIndex].content, { conversationId: f.id, history: prefix, replace: prefix })
  }, [busy, fork, stream])

  const editAndResend = useCallback(async (index: number, next: string) => {
    if (busy) return
    const prefix = messagesRef.current.slice(0, index)
    const f = await fork(index - 1, '编辑后重新提问')
    if (!f) return
    await stream(next, { conversationId: f.id, history: prefix, replace: prefix })
  }, [busy, fork, stream])

  /** Confirm the agent write draft: only now is anything written. */
  const confirmWrite = useCallback(async (draft: AgentWriteDraftResponse, projectId?: number | null) => {
    setWriteBusy(true)
    try {
      const result = await executeAgentWrite(draft.intent, draft.draft)
      toast.success(result.message || '已写入', {
        actions: result.route ? [{ label: '查看', onClick: () => navigate(result.route!) }] : undefined,
      })
      const userEntry: ChatMessage = { role: 'user', content: writeSource }
      const assistantEntry: ChatMessage = {
        role: 'assistant',
        content: result.message || (draft.intent === 'create_note' ? '已创建笔记。' : '已创建任务。'),
      }
      const convId = await ensureConversation(projectId)
      setMessages(prev => [...prev, userEntry, assistantEntry])
      await appendConversationMessages(convId, [userEntry, assistantEntry])
      setWriteDraft(null)
      setWriteSource('')
      void syncEngine.syncAll()
      void qc.invalidateQueries({ queryKey: qk.dashboard })
      refreshLists()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : '写入失败，请检查草案后重试')
    } finally {
      setWriteBusy(false)
    }
  }, [ensureConversation, navigate, qc, refreshLists, writeSource])

  const cancelWrite = useCallback(() => {
    setWriteDraft(null)
    setWriteSource('')
  }, [])

  return {
    messages,
    loadingConversation,
    streaming,
    busy,
    turn,
    send,
    stop,
    branchAt,
    regenerate,
    editAndResend,
    writeDraft,
    setWriteDraft,
    writeBusy,
    confirmWrite,
    cancelWrite,
  }
}
