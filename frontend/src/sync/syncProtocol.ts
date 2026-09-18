import { db as activeDb, type QueuedOperation, type SyncMeta } from '../db/studyDb'
import { deleteLocalGoalChildren } from './enqueueOperation'

export interface ServerEntity {
  id: number
  sync_version?: number
  created_at?: string | null
  updated_at?: string | null
  [key: string]: unknown
}
export interface PushResult { server: ServerEntity }

/** Legacy naive API datetimes mean UTC; date-only domain values are not timestamps. */
export function utcTimestamp(value: unknown): string | null {
  if (typeof value !== 'string' || !/^\d{4}-\d\d-\d\d[T ]/.test(value)) return null
  const iso = value.replace(' ', 'T')
  const qualified = /(?:Z|[+-]\d\d:\d\d)$/i.test(iso) ? iso : `${iso}Z`
  const time = Date.parse(qualified)
  return Number.isFinite(time) ? new Date(time).toISOString() : null
}
export function serverVersion(server: ServerEntity): number | null {
  return Number.isSafeInteger(server.sync_version) && server.sync_version! > 0 ? server.sync_version! : null
}
export function serverMeta(server: ServerEntity) {
  const timestamp = utcTimestamp(server.updated_at) ?? utcTimestamp(server.created_at)
  return { _serverVersion: serverVersion(server), _lastSyncedAt: timestamp, ...(timestamp ? { _updatedAt: timestamp } : {}) }
}

/** Only this transaction may acknowledge a dispatched operation. Never apply its
 * old result to fields edited during the request, or acknowledge a newer queue row. */
export async function acknowledgeOperation(
  op: QueuedOperation,
  result: PushResult | void,
  mapServer?: (server: ServerEntity) => Record<string, unknown>,
  db = activeDb,
): Promise<void> {
  await db.transaction('rw', db.tables, async () => {
    const current = await db.opQueue.get(op.id!)
    if (!current || current.operationId !== op.operationId) return
    const table = db.table(op.module)
    const local = await table.get(op.localId) as SyncMeta | undefined
    if (!local) throw new Error('同步记录已变化，不能确认旧请求')
    await db.opQueue.delete(op.id!)
    if (op.opType === 'delete') {
      if (op.module === 'goals') await deleteLocalGoalChildren(op.localId, local._serverId, db)
      await table.delete(op.localId)
      return
    }
    const remaining = await db.opQueue.where({ module: op.module, localId: op.localId }).toArray()
    remaining.sort((a, b) => a.id! - b.id!)
    const nextStatus = remaining.length ? (remaining[remaining.length - 1].opType === 'delete' ? 'pending_delete' : 'pending_update') : 'synced'
    const server = result?.server
    await table.update(op.localId, {
      ...(server && !remaining.length ? mapServer?.(server) : {}),
      ...(server ? { ...serverMeta(server), _serverId: server.id } : {}),
      ...(remaining.length ? { _updatedAt: local._updatedAt } : {}),
      _syncStatus: nextStatus, _syncError: null, _syncFailedAt: null,
    })
    if (op.module === 'goals' && op.opType === 'create' && server) {
      await db.goalTasks.where('_localGoalId').equals(op.localId).modify({ goal_id: server.id })
    }
  })
}
