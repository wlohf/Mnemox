import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { Conversation, ConversationDetail } from '../services/conversationApi'

const conversationApiMock = vi.hoisted(() => ({
  listConversations: vi.fn(),
  createConversation: vi.fn(),
  getConversation: vi.fn(),
  deleteConversation: vi.fn(),
  updateConversation: vi.fn(),
  listProjects: vi.fn(),
  createProject: vi.fn(),
  updateProject: vi.fn(),
  deleteProject: vi.fn(),
}))

vi.mock('../services/conversationApi', () => conversationApiMock)

import { useChatStore } from './chatStore'

function conversation(id: number): Conversation {
  return {
    id,
    title: `Conversation ${id}`,
    project_id: null,
    is_pinned: false,
    summary: null,
    created_at: '2026-05-18T00:00:00Z',
    updated_at: '2026-05-18T00:00:00Z',
  }
}

function conversationDetail(id: number): ConversationDetail {
  return {
    ...conversation(id),
    messages: [
      {
        id: 1,
        role: 'user',
        content: 'hello',
        image_data: null,
        created_at: '2026-05-18T00:00:00Z',
      },
    ],
  }
}

describe('chatStore conversation restore', () => {
  beforeEach(() => {
    localStorage.clear()
    vi.clearAllMocks()
    useChatStore.setState({
      projects: [],
      activeProjectId: null,
      conversations: [],
      activeConversationId: null,
      messages: [],
      streamingContent: '',
      isStreaming: false,
      searchQuery: '',
    })
    conversationApiMock.listProjects.mockResolvedValue([])
  })

  it('clears a stale persisted conversation before requesting its detail', async () => {
    localStorage.setItem('chat_activeConversationId', '7')
    useChatStore.setState({
      activeConversationId: 7,
      messages: [{ role: 'user', content: 'stale draft' }],
    })
    conversationApiMock.listConversations.mockResolvedValue([conversation(5)])

    const restored = await useChatStore.getState().restoreActiveConversation()

    expect(restored).toBe(false)
    expect(conversationApiMock.getConversation).not.toHaveBeenCalled()
    expect(useChatStore.getState().activeConversationId).toBeNull()
    expect(useChatStore.getState().messages).toEqual([])
    expect(localStorage.getItem('chat_activeConversationId')).toBeNull()
  })

  it('loads detail when the persisted conversation still exists', async () => {
    localStorage.setItem('chat_activeConversationId', '7')
    useChatStore.setState({ activeConversationId: 7 })
    conversationApiMock.listConversations.mockResolvedValue([conversation(7)])
    conversationApiMock.getConversation.mockResolvedValue(conversationDetail(7))

    const restored = await useChatStore.getState().restoreActiveConversation()

    expect(restored).toBe(true)
    expect(conversationApiMock.getConversation).toHaveBeenCalledWith(7)
    expect(useChatStore.getState().messages).toEqual([{ role: 'user', content: 'hello', image_data: undefined }])
  })

  it('clears a stale persisted project before project detail can be requested', async () => {
    localStorage.setItem('chat_activeProjectId', '9999')
    useChatStore.setState({ activeProjectId: 9999 })
    conversationApiMock.listConversations.mockResolvedValue([])
    conversationApiMock.listProjects.mockResolvedValue([{
      id: 1,
      name: 'Real project',
      description: null,
      default_instructions: null,
      color: '#3f4a43',
      is_archived: false,
      conversation_count: 0,
      created_at: '2026-05-18T00:00:00Z',
      updated_at: '2026-05-18T00:00:00Z',
    }])

    await useChatStore.getState().reconcilePersistedSelections()

    expect(useChatStore.getState().activeProjectId).toBeNull()
    expect(localStorage.getItem('chat_activeProjectId')).toBeNull()
  })
})
