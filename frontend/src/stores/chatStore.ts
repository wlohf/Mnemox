import { create } from 'zustand'
import type { ChatMessage } from '../services/chatApi'
import { getApiErrorMessage } from '../services/apiClient'
import {
  listConversations,
  createConversation,
  getConversation,
  deleteConversation as apiDeleteConversation,
  updateConversation,
  listProjects,
  createProject as apiCreateProject,
  updateProject as apiUpdateProject,
  deleteProject as apiDeleteProject,
  type Conversation,
  type ChatProject,
} from '../services/conversationApi'

interface ChatStore {
  // Projects
  projects: ChatProject[]
  activeProjectId: number | null

  // Conversations
  conversations: Conversation[]
  activeConversationId: number | null
  lastConversationError: string | null

  // Messages
  messages: ChatMessage[]
  streamingContent: string
  isStreaming: boolean

  // Search
  searchQuery: string

  // Actions - Projects
  loadProjects: () => Promise<void>
  createProject: (name: string, description?: string, defaultInstructions?: string, color?: string) => Promise<ChatProject>
  updateProject: (id: number, data: { name?: string; description?: string; default_instructions?: string; color?: string }) => Promise<void>
  deleteProject: (id: number) => Promise<void>
  setActiveProjectId: (id: number | null) => void

  // Actions - Conversations
  loadConversations: (projectId?: number | null, search?: string) => Promise<Conversation[]>
  createNewConversation: (projectId?: number | null) => Promise<Conversation>
  reconcilePersistedSelections: () => Promise<void>
  restoreActiveConversation: () => Promise<boolean>
  setActiveConversation: (id: number | null) => Promise<boolean>
  deleteConversation: (id: number) => Promise<void>
  renameConversation: (id: number, title: string) => Promise<void>
  moveConversation: (id: number, projectId: number | null) => Promise<void>
  pinConversation: (id: number, pinned: boolean) => Promise<void>
  searchConversations: (query: string) => Promise<void>
  reloadConversationsForCurrentView: () => Promise<void>
  clearConversationError: () => void

  // Actions - Messages
  setMessages: (messages: ChatMessage[]) => void
  addMessage: (message: ChatMessage) => void
  setStreamingContent: (content: string) => void
  setIsStreaming: (streaming: boolean) => void
  clearMessages: () => void
}

// Restore persisted IDs
const getPersistedId = (key: string): number | null => {
  try {
    const val = localStorage.getItem(key)
    return val ? Number(val) : null
  } catch {
    return null
  }
}

const persistId = (key: string, val: number | null) => {
  try {
    if (val !== null) {
      localStorage.setItem(key, String(val))
    } else {
      localStorage.removeItem(key)
    }
  } catch {
    // ignore
  }
}

// Debounce timer for search
let _searchDebounceTimer: ReturnType<typeof setTimeout> | null = null
// Monotonic token so concurrent detail loads only apply the latest selection.
let _activeConversationRequestId = 0

export const useChatStore = create<ChatStore>((set, get) => ({
  projects: [],
  activeProjectId: getPersistedId('chat_activeProjectId'),
  conversations: [],
  activeConversationId: getPersistedId('chat_activeConversationId'),
  lastConversationError: null,
  messages: [],
  streamingContent: '',
  isStreaming: false,
  searchQuery: '',

  // ---- Projects ----

  loadProjects: async () => {
    const projects = await listProjects()
    set({ projects })
  },

  createProject: async (name, description, defaultInstructions, color) => {
    const project = await apiCreateProject({
      name,
      description,
      default_instructions: defaultInstructions,
      color,
    })
    await get().loadProjects()
    return project
  },

  updateProject: async (id, data) => {
    await apiUpdateProject(id, data)
    await get().loadProjects()
  },

  deleteProject: async (id) => {
    await apiDeleteProject(id)
    if (get().activeProjectId === id) {
      set({ activeProjectId: null })
      persistId('chat_activeProjectId', null)
    }
    await get().loadProjects()
    await get().loadConversations()
  },

  setActiveProjectId: (id) => {
    set({ activeProjectId: id })
    persistId('chat_activeProjectId', id)
  },

  // ---- Conversations ----

  // Keep the list aligned with current sidebar view (project filter/search).
  reloadConversationsForCurrentView: async () => {
    const { activeProjectId, searchQuery, loadConversations } = get()
    if (searchQuery.trim()) {
      await loadConversations(undefined, searchQuery)
      return
    }
    if (activeProjectId !== null) {
      await loadConversations(activeProjectId)
      return
    }
    await loadConversations()
  },

  loadConversations: async (projectId, search) => {
    const params: { project_id?: number; search?: string } = {}
    if (projectId !== undefined && projectId !== null) {
      params.project_id = projectId
    }
    if (search) {
      params.search = search
    }
    const conversations = await listConversations(params)
    set({ conversations })
    return conversations
  },

  reconcilePersistedSelections: async () => {
    const { activeProjectId, activeConversationId } = get()
    let projects: ChatProject[] = []
    try {
      await get().loadConversations()
      projects = await listProjects()
      set({ projects })
    } catch (error) {
      throw new Error(getApiErrorMessage(error, '加载对话失败，请检查后端服务'))
    }

    if (activeProjectId !== null && !projects.some((project) => project.id === activeProjectId)) {
      set({ activeProjectId: null })
      persistId('chat_activeProjectId', null)
    }

    // List endpoint is paginated; a missing ID in the first page is not proof that
    // the conversation is gone. Verify via detail lookup before clearing.
    if (activeConversationId !== null) {
      try {
        await getConversation(activeConversationId)
      } catch (error) {
        const status = typeof error === 'object' && error && 'status' in error
          ? Number((error as { status?: number }).status)
          : undefined
        if (status === 404) {
          set({ activeConversationId: null, messages: [], streamingContent: '', lastConversationError: null })
          persistId('chat_activeConversationId', null)
        }
      }
    }
  },

  createNewConversation: async (projectId) => {
    const state = get()
    // 已在一个空对话中，直接返回当前对话
    if (state.activeConversationId !== null && state.messages.length === 0) {
      const current = state.conversations.find((c) => c.id === state.activeConversationId)
      if (current) return current
    }
    const conv = await createConversation({
      title: '新对话',
      project_id: projectId ?? undefined,
    })
    await get().loadConversations()
    set({ activeConversationId: conv.id, messages: [], streamingContent: '' })
    persistId('chat_activeConversationId', conv.id)
    return conv
  },

  restoreActiveConversation: async () => {
    await get().reconcilePersistedSelections()
    const id = get().activeConversationId
    if (!id) {
      return false
    }

    return get().setActiveConversation(id)
  },

  setActiveConversation: async (id) => {
    const requestId = ++_activeConversationRequestId
    const previousId = get().activeConversationId
    const previousMessages = get().messages
    set({ activeConversationId: id, lastConversationError: null })
    persistId('chat_activeConversationId', id)

    if (id) {
      try {
        const detail = await getConversation(id)
        // A newer selection won the race; discard this response.
        if (requestId !== _activeConversationRequestId) {
          return false
        }
        set({
          messages: detail.messages.map((m) => ({
            role: m.role as 'user' | 'assistant',
            content: m.content,
            image_data: m.image_data || undefined,
          })),
          streamingContent: '',
          lastConversationError: null,
        })
        return true
      } catch (error) {
        if (requestId !== _activeConversationRequestId) {
          return false
        }
        const message = getApiErrorMessage(error, '加载历史对话失败，请稍后重试')
        const fallbackId = previousId === id ? null : previousId
        set({
          activeConversationId: fallbackId,
          messages: fallbackId ? previousMessages : [],
          streamingContent: '',
          lastConversationError: message,
        })
        persistId('chat_activeConversationId', fallbackId)
        return false
      }
    }

    if (requestId !== _activeConversationRequestId) {
      return false
    }
    set({ messages: [], streamingContent: '', lastConversationError: null })
    return true
  },

  clearConversationError: () => set({ lastConversationError: null }),

  deleteConversation: async (id) => {
    await apiDeleteConversation(id)
    if (get().activeConversationId === id) {
      set({ activeConversationId: null, messages: [], streamingContent: '' })
      persistId('chat_activeConversationId', null)
    }
    await get().reloadConversationsForCurrentView()
  },

  renameConversation: async (id, title) => {
    await updateConversation(id, { title })
    await get().reloadConversationsForCurrentView()
  },

  moveConversation: async (id, projectId) => {
    await updateConversation(id, { project_id: projectId })
    await get().reloadConversationsForCurrentView()
  },

  pinConversation: async (id, pinned) => {
    await updateConversation(id, { is_pinned: pinned })
    await get().reloadConversationsForCurrentView()
  },

  searchConversations: async (query) => {
    set({ searchQuery: query })
    // Debounce the actual API call by 300ms
    if (_searchDebounceTimer) {
      clearTimeout(_searchDebounceTimer)
    }
    _searchDebounceTimer = setTimeout(async () => {
      if (query.trim()) {
        await get().loadConversations(undefined, query)
      } else {
        await get().loadConversations()
      }
    }, 300)
  },

  // ---- Messages ----

  setMessages: (messages) => set({ messages }),
  addMessage: (message) => set((s) => ({ messages: [...s.messages, message] })),
  setStreamingContent: (content) => set({ streamingContent: content }),
  setIsStreaming: (streaming) => set({ isStreaming: streaming }),
  clearMessages: () => set({ messages: [], streamingContent: '' }),
}))
