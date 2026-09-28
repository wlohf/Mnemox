import { db as activeDb, type LocalAnkiCard } from '../db/studyDb'
import { enqueueOperation, saveLocalOperation } from '../sync/enqueueOperation'

export async function createLocalAnkiCard(data: { front: string; back: string; tags?: string; note?: string }, db = activeDb) {
  const now = new Date().toISOString()
  const record: LocalAnkiCard = {
    _localId: crypto.randomUUID(), _serverId: null, _syncStatus: 'pending_create', _updatedAt: now,
    _lastSyncedAt: null, _conflictAt: null, _conflictServerData: null,
    front: data.front, back: data.back, tags: data.tags || null, note: data.note || null, source: 'manual',
    due_at: now, interval_days: 0, ease_factor: 250, repetitions: 0, last_quality: null, created_at: now,
  }
  const saved = await saveLocalOperation<LocalAnkiCard>('ankiCards', 'create', record._localId, record, db)
  if (!saved) throw new Error('卡片未能保存到本机')
  return saved
}

export async function queueAnkiReview(localId: string, quality: number, db = activeDb) {
  if (!Number.isInteger(quality) || quality < 0 || quality > 5) throw new Error('评分必须在 0–5 之间')
  await db.transaction('rw', db.tables, async () => {
    const card = await db.ankiCards.get(localId)
    if (!card || card._syncStatus === 'pending_delete') throw new Error('卡片已删除')
    if (card._syncStatus === 'conflicted') throw new Error('请先在账户菜单处理该卡片的同步冲突')
    const operations = await db.opQueue.where({ module: 'ankiCards', localId }).toArray()
    if (operations.some(op => op.opType === 'update')) throw new Error('卡片编辑尚未同步，请同步完成后再复习')
    if (operations.some(op => op.opType === 'review')) return // Double clicks share one durable attempt.
    await db.ankiCards.update(localId, { _localRevision: (card._localRevision ?? 0) + 1, _updatedAt: new Date().toISOString() })
    await enqueueOperation('ankiCards', 'review', localId, { quality, reviewed_at: new Date().toISOString() }, db)
  })
}
