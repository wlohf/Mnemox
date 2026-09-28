import { afterEach, expect, it, vi } from 'vitest'
import { sendMessageStream } from './chatApi'
import { setApiSessionUser } from './sessionScope'

afterEach(() => { vi.unstubAllGlobals(); setApiSessionUser(null) })

it('only reports success after the explicit server completion marker', async () => {
  const chunk = vi.fn(), done = vi.fn(), error = vi.fn()
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('data: {"content":"partial"}\n\n')))
  await sendMessageStream('question', [], chunk, done, error)
  expect(chunk).toHaveBeenCalledWith('partial')
  expect(done).not.toHaveBeenCalled()
  expect(error).toHaveBeenCalledWith(expect.stringContaining('中断'))
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('data: {"content":"complete"}\n\ndata: [DONE]\n\n')))
  await sendMessageStream('question', [], chunk, done, error)
  expect(done).toHaveBeenCalledOnce()
})

it('binds the stream to its account and does not complete a cancelled stream', async () => {
  setApiSessionUser(7)
  const done = vi.fn(), error = vi.fn(), controller = new AbortController()
  const fetch = vi.fn().mockRejectedValue(new DOMException('Stopped', 'AbortError'))
  vi.stubGlobal('fetch', fetch)
  await sendMessageStream('q', [], vi.fn(), done, error, undefined, undefined, controller.signal)
  expect(fetch.mock.calls[0][1].headers['X-Mnemox-User-Id']).toBe('7')
  expect(done).not.toHaveBeenCalled()
  expect(error).toHaveBeenCalledWith(expect.stringContaining('停止'))
})

it('ignores a late response when the account changed while fetch was pending', async () => {
  setApiSessionUser(7)
  let resolveFetch!: (response: Response) => void
  vi.stubGlobal('fetch', vi.fn(() => new Promise<Response>(resolve => { resolveFetch = resolve })))
  const chunk = vi.fn(), done = vi.fn(), error = vi.fn()
  const pending = sendMessageStream('q', [], chunk, done, error)
  setApiSessionUser(8)
  resolveFetch(new Response('data: {"content":"account 7 private reply"}\n\ndata: [DONE]\n\n'))
  await pending
  expect(chunk).not.toHaveBeenCalled()
  expect(done).not.toHaveBeenCalled()
  expect(error).not.toHaveBeenCalled()
})
