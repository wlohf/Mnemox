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
      lastConversationError: null,
      messages: [],
      streamingContent: '',
      isStreaming: false,
      searchQuery: '',
    })
    conversationApiMock.listProjects.mockResolvedValue([])
  })

  it('clears a stale persisted conversation after detail lookup returns 404', async () => {
    localStorage.setItem('chat_activeConversationId', '7')
    useChatStore.setState({
      activeConversationId: 7,
      messages: [{ role: 'user', content: 'stale draft' }],
    })
    conversationApiMock.listConversations.mockResolvedValue([conversation(5)])
    conversationApiMock.getConversation.mockRejectedValue(Object.assign(new Error('对话不存在'), { status: 404 }))

    const restored = await useChatStore.getState().restoreActiveConversation()

    expect(restored).toBe(false)
    expect(conversationApiMock.getConversation).toHaveBeenCalledWith(7)
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

  it('switches to a clicked historical conversation and persists it', async () => {
    useChatStore.setState({
      activeConversationId: 5,
      messages: [{ role: 'assistant', content: 'old chat' }],
    })
    conversationApiMock.getConversation.mockResolvedValue(conversationDetail(9))

    const switched = await useChatStore.getState().setActiveConversation(9)

    expect(switched).toBe(true)
    expect(conversationApiMock.getConversation).toHaveBeenCalledWith(9)
    expect(useChatStore.getState().activeConversationId).toBe(9)
    expect(useChatStore.getState().messages).toEqual([{ role: 'user', content: 'hello', image_data: undefined }])
    expect(localStorage.getItem('chat_activeConversationId')).toBe('9')
  })

  it('keeps the current conversation selected when historical conversation loading fails', async () => {
    useChatStore.setState({
      activeConversationId: 5,
      messages: [{ role: 'assistant', content: 'old chat' }],
    })
    conversationApiMock.getConversation.mockRejectedValue(new Error('not found'))

    const switched = await useChatStore.getState().setActiveConversation(9)

    expect(switched).toBe(false)
    expect(useChatStore.getState().activeConversationId).toBe(5)
    expect(useChatStore.getState().messages).toEqual([{ role: 'assistant', content: 'old chat' }])
    expect(localStorage.getItem('chat_activeConversationId')).toBe('5')
    expect(useChatStore.getState().lastConversationError).toContain('not found')
  })

  it('ignores a slower stale detail response after a newer conversation is selected', async () => {
    useChatStore.setState({
      activeConversationId: 5,
      messages: [{ role: 'assistant', content: 'old chat' }],
    })

    let resolveSlow: (value: ConversationDetail) => void = () => {}
    conversationApiMock.getConversation.mockImplementation((id: number) => {
      if (id === 9) {
        return new Promise<ConversationDetail>((resolve) => {
          resolveSlow = resolve
        })
      }
      return Promise.resolve(conversationDetail(id))
    })

    const slowPromise = useChatStore.getState().setActiveConversation(9)
    const fastOk = await useChatStore.getState().setActiveConversation(11)
    expect(fastOk).toBe(true)
    expect(useChatStore.getState().activeConversationId).toBe(11)
    expect(useChatStore.getState().messages).toEqual([{ role: 'user', content: 'hello', image_data: undefined }])

    resolveSlow(conversationDetail(9))
    const slowOk = await slowPromise

    expect(slowOk).toBe(false)
    expect(useChatStore.getState().activeConversationId).toBe(11)
    expect(useChatStore.getState().messages).toEqual([{ role: 'user', content: 'hello', image_data: undefined }])
    expect(localStorage.getItem('chat_activeConversationId')).toBe('11')
  })

  it('does not clear a valid active conversation just because it is outside the first list page', async () => {
    localStorage.setItem('chat_activeConversationId', '77')
    useChatStore.setState({
      activeConversationId: 77,
      messages: [{ role: 'user', content: 'still valid' }],
    })
    conversationApiMock.listConversations.mockResolvedValue([conversation(1), conversation(2)])
    conversationApiMock.getConversation.mockResolvedValue(conversationDetail(77))

    await useChatStore.getState().reconcilePersistedSelections()

    expect(useChatStore.getState().activeConversationId).toBe(77)
    expect(localStorage.getItem('chat_activeConversationId')).toBe('77')
    expect(conversationApiMock.getConversation).toHaveBeenCalledWith(77)
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
