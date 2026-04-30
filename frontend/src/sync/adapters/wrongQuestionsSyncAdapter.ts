import { db, type LocalWrongQuestion, type QueuedOperation } from '../../db/studyDb'
import type { ModuleSyncAdapter } from '../SyncEngine'
import { apiFetch } from '../../services/apiClient'
import type { WrongQuestionItem } from '../../services/wrongQuestionApi'

export const wrongQuestionsSyncAdapter: ModuleSyncAdapter = {
  module: 'wrongQuestions',

  async pushCreate(op: QueuedOperation) {
    const payload = JSON.parse(op.payload) as Record<string, unknown>
    const server = await apiFetch<WrongQuestionItem>('/api/wrong-questions', {
      method: 'POST',
      body: JSON.stringify(payload),
    })
    await db.wrongQuestions.update(op.localId, {
      _serverId: server.id,
      _syncStatus: 'synced',
      _lastSyncedAt: new Date().toISOString(),
    })
  },

  async pushUpdate(op: QueuedOperation) {
    const local = await db.wrongQuestions.get(op.localId)
    if (!local?._serverId) throw new Error('no serverId')
    const payload = JSON.parse(op.payload) as Record<string, unknown>
    await apiFetch<WrongQuestionItem>(`/api/wrong-questions/${local._serverId}`, {
      method: 'PUT',
      body: JSON.stringify(payload),
    })
    await db.wrongQuestions.update(op.localId, { _syncStatus: 'synced', _lastSyncedAt: new Date().toISOString() })
  },

  async pushDelete(op: QueuedOperation) {
    const local = await db.wrongQuestions.get(op.localId)
    if (!local) return
    if (local._serverId) {
      try { await apiFetch(`/api/wrong-questions/${local._serverId}`, { method: 'DELETE' }) } catch { /* 404 ok */ }
    }
    await db.wrongQuestions.delete(op.localId)
  },

  async pullAll() {
    const serverItems = await apiFetch<WrongQuestionItem[]>('/api/wrong-questions')
    const serverMap = new Map(serverItems.map((q) => [q.id, q]))
    const allLocal = await db.wrongQuestions.toArray()
    const localByServerId = new Map<number, LocalWrongQuestion>()
    for (const l of allLocal) { if (l._serverId != null) localByServerId.set(l._serverId, l) }

    for (const sq of serverItems) {
      const local = localByServerId.get(sq.id)
      const updatedAt = sq.created_at ?? new Date().toISOString()
      if (!local) {
        await db.wrongQuestions.put({
          _localId: crypto.randomUUID(), _serverId: sq.id, _syncStatus: 'synced',
          _updatedAt: updatedAt, _lastSyncedAt: new Date().toISOString(),
          _conflictAt: null, _conflictServerData: null,
          content: sq.content, question_type: sq.question_type ?? null,
          answer: sq.answer ?? null, explanation: sq.explanation ?? null,
          difficulty: sq.difficulty ?? null, chapter_id: sq.chapter_id ?? null,
          chapter_title: sq.chapter_title, wrong_count: sq.wrong_count,
          mastery_status: sq.mastery_status, review_count: sq.review_count,
          knowledge_point: sq.knowledge_point ?? null,
          next_review_at: sq.next_review_at ?? null,
          last_wrong_at: sq.last_wrong_at ?? null, created_at: sq.created_at ?? null,
        })
      } else if (local._syncStatus === 'synced') {
        await db.wrongQuestions.update(local._localId, {
          mastery_status: sq.mastery_status, review_count: sq.review_count,
          wrong_count: sq.wrong_count, next_review_at: sq.next_review_at ?? null,
          _updatedAt: updatedAt, _lastSyncedAt: new Date().toISOString(),
        })
      }
    }

    for (const local of allLocal) {
      if (local._serverId != null && local._syncStatus === 'synced' && !serverMap.has(local._serverId)) {
        await db.wrongQuestions.delete(local._localId)
      }
    }
  },
}
