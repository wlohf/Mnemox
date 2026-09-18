import { db as activeDb, type ModuleName, type QueuedOperation, type OpType, type SyncMeta } from '../db/studyDb'

/** Queue changes share the caller's Dexie transaction, or create their own. */
export async function enqueueOperation(
  module: ModuleName,
  opType: OpType,
  localId: string,
  payload: Record<string, unknown> = {},
  db = activeDb,
): Promise<void> {
  await db.transaction('rw', db.tables, async () => {
    const existing = (await db.opQueue.where({ module, localId }).toArray()).sort((a, b) => a.id! - b.id!)
    const last = existing[existing.length - 1]
    const table = db.table(module)
    const local = await table.get(localId) as SyncMeta | undefined
    const uncertain = existing.some(op => op.claimedAt || op.legacyUncertain)

    // A create that has ever been claimed may already exist remotely, even if
    // _serverId is still null. Keep its row and append a compensating delete.
    if (opType === 'delete' && !local?._serverId && !uncertain) {
      if (module === 'goals') await deleteLocalGoalChildren(localId, local?._serverId ?? null, db)
      await db.opQueue.bulkDelete(existing.map(op => op.id!))
      await table.delete(localId)
      return
    }
    if (!local) throw new Error('找不到待同步的本地记录')
    if (opType === 'delete' && last?.opType === 'delete') return

    if (last && !last.claimedAt && !last.legacyUncertain && last.opType === 'update' && opType === 'update') {
      await db.opQueue.update(last.id!, {
        payload: JSON.stringify({ ...JSON.parse(last.payload), ...payload }),
        failedAt: null, lastError: null,
      })
    } else {
      await db.opQueue.add({
        module, opType, localId, payload: JSON.stringify(payload),
        operationId: crypto.randomUUID(), claimedAt: null,
        createdAt: new Date().toISOString(),
      })
    }
    // An edit can request another attempt, but must never change an already
    // dispatched operation's payload, destination, revision or identity.
    for (const op of existing) {
      if (op.failedAt && !op.legacyUncertain) await db.opQueue.update(op.id!, { failedAt: null, lastError: null })
    }
    await table.update(localId, {
      _syncStatus: opType === 'delete' ? 'pending_delete' : local._serverId ? 'pending_update' : 'pending_create',
      _syncError: null, _syncFailedAt: null,
    })
  })
}

/** The only offline write boundary: domain row + intent commit or roll back together. */
export async function saveLocalOperation<T extends SyncMeta>(
  module: ModuleName,
  opType: OpType,
  localId: string,
  payload: Record<string, unknown> | T = {},
  db = activeDb,
): Promise<T | undefined> {
  return db.transaction('rw', db.tables, async () => {
    const table = db.table(module)
    const existing = await table.get(localId) as T | undefined
    if (opType !== 'create' && !existing) return undefined
    if (existing?._syncStatus === 'conflicted') throw new Error('这条记录存在同步冲突，请先在账户菜单中处理')
    if (opType === 'update' && existing?._syncStatus === 'pending_delete') throw new Error('这条记录正在删除，不能继续编辑')
    const now = new Date().toISOString()
    if (opType === 'create') {
      if (module === 'goalTasks' && '_localGoalId' in payload && payload._localGoalId) {
        const parent = await db.goals.get(String(payload._localGoalId))
        if (!parent || parent._syncStatus === 'pending_delete') throw new Error('父目标已删除或正在删除，不能添加任务')
      }
      await table.add({ ...payload, _localId: localId, _serverId: null, _serverVersion: null, _localRevision: 1, _updatedAt: now })
    } else {
      const fields = Object.fromEntries(Object.entries(payload).filter(([key]) => !key.startsWith('_')))
      await table.update(localId, {
        ...(opType === 'update' ? fields : {}),
        _updatedAt: now, _localRevision: (existing?._localRevision ?? 0) + 1,
      })
    }
    await enqueueOperation(module, opType, localId, payload as Record<string, unknown>, db)
    return opType === 'delete' ? existing : await table.get(localId) as T | undefined
  })
}

/** Goal deletion explicitly includes its children; use within a caller-owned transaction. */
export async function deleteLocalGoalChildren(localId: string, serverId: number | null, db = activeDb) {
  const children = await db.goalTasks.filter(task => task._localGoalId === localId || (serverId !== null && task.goal_id === serverId)).toArray()
  for (const child of children) {
    await db.opQueue.where({ module: 'goalTasks', localId: child._localId }).delete()
    await db.goalTasks.delete(child._localId)
  }
}

/** Claim under the same IDB write lock used by enqueue. Claims survive restarts. */
export async function claimOperation(id: number, db = activeDb): Promise<QueuedOperation | undefined> {
  return db.transaction('rw', db.tables, async () => {
    const op = await db.opQueue.get(id)
    if (!op || op.legacyUncertain) return undefined
    const predecessors = await db.opQueue.where({ module: op.module, localId: op.localId }).toArray()
    if (predecessors.some(other => other.id! < id)) return undefined
    const local = await db.table(op.module).get(op.localId)
    if (local?._syncStatus === 'conflicted') return undefined
    if (op.claimedAt) return op
    if (!local) throw new Error('找不到待同步的本地记录，请先核对云端')
    if (op.opType !== 'create' && !local._serverId) throw new Error('前置创建尚未确认，不能修改或删除')
    if (op.module === 'goalTasks' && op.opType === 'create' && !local.goal_id) throw new Error('父目标尚未同步')
    const claimed = {
      ...op, operationId: op.operationId ?? crypto.randomUUID(), claimedAt: new Date().toISOString(),
      serverId: local._serverId, expectedVersion: local._serverVersion ?? null,
      parentServerId: local.goal_id ?? null,
    }
    await db.opQueue.put(claimed)
    return claimed
  })
}
