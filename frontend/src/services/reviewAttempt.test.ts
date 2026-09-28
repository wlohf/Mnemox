import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { setApiSessionUser } from './sessionScope'
import { beginReviewAttempt, pendingReviewAttempt, submitReviewAttempt } from './reviewAttempt'

beforeEach(() => { localStorage.clear(); setApiSessionUser(7) })
afterEach(() => { vi.unstubAllGlobals(); setApiSessionUser(null) })

it('retains the attempt across lost responses and blocks changed scores until reconciled', async () => {
  const fetch = vi.fn().mockRejectedValueOnce(new TypeError('response lost'))
    .mockResolvedValue(new Response(JSON.stringify({ score: 85 }), { headers: { 'Content-Type': 'application/json' } }))
  vi.stubGlobal('fetch', fetch)
  const path = '/api/review/tasks/1/complete'
  await expect(submitReviewAttempt(path, { quality: 5, coach_action_attempt_id: 'coach-original' })).rejects.toThrow()
  const id = pendingReviewAttempt(path)!.id
  beginReviewAttempt(path)
  expect(pendingReviewAttempt(path)!.id).toBe(id)
  await expect(submitReviewAttempt(path, { quality: 1 })).rejects.toThrow('相同评分')
  await submitReviewAttempt(path, { quality: 5 })
  expect(JSON.parse(fetch.mock.calls[1][1].body).attempt_id).toBe(id)
  expect(JSON.parse(fetch.mock.calls[1][1].body).coach_action_attempt_id).toBe('coach-original')
  expect(pendingReviewAttempt(path)!.done).toBe(true)
  beginReviewAttempt(path)
  expect(pendingReviewAttempt(path)).toBeNull()
})

it('never restores another account attempt', async () => {
  vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('offline')))
  await expect(submitReviewAttempt('/review', { quality: 5 })).rejects.toThrow()
  setApiSessionUser(8)
  expect(pendingReviewAttempt('/review')).toBeNull()
})
