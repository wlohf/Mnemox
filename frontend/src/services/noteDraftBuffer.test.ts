import { afterEach, describe, expect, it, vi } from 'vitest'
import { NoteDraftBuffer } from './noteDraftBuffer'

afterEach(() => vi.useRealTimers())
describe('note drafts across navigation', () => {
  it('flushes the latest unsaved edit before switching notes or unmounting', () => {
    vi.useFakeTimers()
    const storage = { setItem: vi.fn() }
    const buffer = new NoteDraftBuffer(storage, vi.fn())
    buffer.schedule('a', { content: 'first' }, vi.fn())
    vi.advanceTimersByTime(200)
    buffer.schedule('a', { content: 'last sentence' }, vi.fn())
    buffer.flush()
    expect(JSON.parse(storage.setItem.mock.calls[0][1])).toMatchObject({ content: 'last sentence' })
    buffer.schedule('b', { content: 'other note' }, vi.fn())
    vi.advanceTimersByTime(700)
    expect(storage.setItem.mock.calls.map(call => call[0])).toEqual(['a', 'b'])
  })
  it('does not resurrect a draft after an explicit save', () => {
    vi.useFakeTimers()
    const storage = { setItem: vi.fn() }
    const buffer = new NoteDraftBuffer(storage, vi.fn())
    buffer.schedule('a', { content: 'saved' }, vi.fn())
    buffer.discard('a')
    buffer.flush()
    vi.runAllTimers()
    expect(storage.setItem).not.toHaveBeenCalled()
  })
  it('retains the pending edit and reports storage failure', () => {
    const storage = { setItem: vi.fn().mockImplementationOnce(() => { throw new Error('quota') }) }
    const error = vi.fn(), saved = vi.fn()
    const buffer = new NoteDraftBuffer(storage, error)
    buffer.schedule('a', { content: 'retained' }, saved)
    expect(buffer.flush()).toBe(false)
    expect(saved).not.toHaveBeenCalled()
    expect(error).toHaveBeenCalledOnce()
    expect(buffer.flush()).toBe(true)
    expect(saved).toHaveBeenCalledOnce()
  })
})
