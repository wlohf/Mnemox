import { describe, expect, it } from 'vitest'
import { getConversationPath, parseConversationRouteId } from './conversationRoute'

describe('conversation route helpers', () => {
  it('builds stable paths for historical conversations', () => {
    expect(getConversationPath(42)).toBe('/conversations/42')
  })

  it('parses only positive integer conversation ids', () => {
    expect(parseConversationRouteId('42')).toBe(42)
    expect(parseConversationRouteId('0')).toBeNull()
    expect(parseConversationRouteId('-1')).toBeNull()
    expect(parseConversationRouteId('abc')).toBeNull()
    expect(parseConversationRouteId(undefined)).toBeNull()
  })
})
