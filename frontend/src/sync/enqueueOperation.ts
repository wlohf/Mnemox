import { db, type ModuleName, type QueuedOperation, type OpType } from '../db/studyDb'

/**
 * Enqueue an operation with merge logic to reduce redundant network calls.
 *
 * Merge rules (same module + same localId):
 *   create + update → update the create's payload
 *   create + delete → remove both (never pushed)
 *   update + update → merge into single update
 *   update + delete → replace with delete
 *   (anything) + create → shouldn't happen, just append
 */
export async function enqueueOperation(
  module: ModuleName,
  opType: OpType,
  localId: string,
  payload: Record<string, unknown> = {},
): Promise<void> {
  const existing = await db.opQueue
    .where({ module, localId })
    .toArray()

  // Sort by id so we process in order
  existing.sort((a, b) => (a.id ?? 0) - (b.id ?? 0))

  const last = existing.length > 0 ? existing[existing.length - 1] : null
  const nextSyncStatus =
    opType === 'delete' ? 'pending_delete' : last?.opType === 'create' || opType === 'create' ? 'pending_create' : 'pending_update'

  await db.table(module).update(localId, {
    _syncStatus: nextSyncStatus,
    _syncError: null,
    _syncFailedAt: null,
  })

  if (last) {
    if (last.opType === 'create' && opType === 'update') {
      // Merge update payload into the create payload
      const merged = { ...JSON.parse(last.payload), ...payload }
      await db.opQueue.update(last.id!, { payload: JSON.stringify(merged), failedAt: null, lastError: null })
      return
    }

    if (last.opType === 'create' && opType === 'delete') {
      // Record was never pushed — just remove all pending ops for this localId
      const ids = existing.map((e) => e.id!).filter(Boolean)
      await db.opQueue.bulkDelete(ids)
      return
    }

    if (last.opType === 'update' && opType === 'update') {
      // Merge updates
      const merged = { ...JSON.parse(last.payload), ...payload }
      await db.opQueue.update(last.id!, { payload: JSON.stringify(merged), failedAt: null, lastError: null })
      return
    }

    if (last.opType === 'update' && opType === 'delete') {
      // Replace update with delete
      const ids = existing.map((e) => e.id!).filter(Boolean)
      await db.opQueue.bulkDelete(ids)
      // fall through to add a delete op
    }
  }

  const op: QueuedOperation = {
    module,
    opType,
    localId,
    payload: JSON.stringify(payload),
    createdAt: new Date().toISOString(),
  }
  await db.opQueue.add(op)
}
