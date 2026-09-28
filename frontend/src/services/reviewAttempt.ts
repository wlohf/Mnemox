import { db } from '../db/studyDb'
import { apiFetch } from './apiClient'
import { captureApiSession } from './sessionScope'

interface SavedAttempt { id: string; body: Record<string, unknown>; done: boolean }
const keyFor = (path: string) => `mnemox.review-attempt:${captureApiSession().userId}:${db.name}:${path}`

export function pendingReviewAttempt(path: string): SavedAttempt | null {
  const raw = localStorage.getItem(keyFor(path))
  return raw ? JSON.parse(raw) as SavedAttempt : null
}

/** Called when the learner explicitly opens another review, never on request retry. */
export function beginReviewAttempt(path: string) {
  if (pendingReviewAttempt(path)?.done) localStorage.removeItem(keyFor(path))
}

export async function submitReviewAttempt<T>(path: string, body: Record<string, unknown>): Promise<T> {
  const scope = captureApiSession()
  const key = keyFor(path)
  let attempt = pendingReviewAttempt(path)
  // Reopening the review outside its original Coach URL must still retry the
  // original attempt. Answers/quality remain immutable; only restore context.
  if (attempt?.body.coach_action_attempt_id && body.coach_action_attempt_id == null) {
    body = { ...body, coach_action_attempt_id: attempt.body.coach_action_attempt_id }
  }
  if (attempt && JSON.stringify(attempt.body) !== JSON.stringify(body)) {
    const grade = attempt.body.quality
    throw new Error(grade !== undefined
      ? `上次评分 ${grade} 的结果尚未确认，请用相同评分重试`
      : '上次答案的结果尚未确认，请保留原答案重试；重新打开复习可恢复原答案')
  }
  if (!attempt) {
    attempt = { id: crypto.randomUUID(), body, done: false }
    // Persist before sending. If local storage fails, do not make an unrepeatable submission.
    localStorage.setItem(key, JSON.stringify(attempt))
  }
  const response = await apiFetch<T>(path, {
    method: 'POST', body: JSON.stringify({ ...attempt.body, attempt_id: attempt.id }),
  }, scope)
  scope.assertActive()
  localStorage.setItem(key, JSON.stringify({ ...attempt, done: true }))
  return response
}
