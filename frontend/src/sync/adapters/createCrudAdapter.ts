import { db as activeDb, type ModuleName, type QueuedOperation, type SyncMeta } from '../../db/studyDb'
import { scopedApiFetch } from '../../services/apiClient'
import type { ModuleSyncAdapter } from '../SyncEngine'
import { serverMeta, serverVersion, type ServerEntity } from '../syncProtocol'

type ScopedFetch = ReturnType<typeof scopedApiFetch>
interface Config {
  module: ModuleName
  collection: string
  item?: (id: number) => string
  createUrl?: (op: QueuedOperation) => string
  createBody: (payload: Record<string, unknown>) => Record<string, unknown>
  updateBody: (payload: Record<string, unknown>) => Record<string, unknown>
  mapServer: (server: ServerEntity) => Record<string, unknown>
  list?: (fetch: ScopedFetch, db: typeof activeDb) => Promise<ServerEntity[]>
  completeSnapshot?: boolean
}

export function pick(source: Record<string, unknown>, keys: string[]): Record<string, unknown> {
  return Object.fromEntries(keys.filter(key => source[key] !== undefined).map(key => [key, source[key]]))
}

async function requireProtocol(fetch: ScopedFetch) {
  let capabilities: { protocol_version: number }
  try {
    capabilities = await fetch('/api/sync/capabilities')
  } catch (error) {
    if ((error as { status?: number }).status !== 404) throw error
    capabilities = { protocol_version: 0 }
  }
  if (capabilities.protocol_version !== 1) {
    throw Object.assign(new Error('服务器不支持安全同步协议，请先升级服务器'), { status: 426 })
  }
}

function headers(op: QueuedOperation): Record<string, string> {
  if (!op.operationId || !op.claimedAt) throw new Error('同步操作尚未领取')
  return {
    'Idempotency-Key': op.operationId,
    // A legacy local row without a known version must require a user decision;
    // never adopt a just-fetched remote version and overwrite it automatically.
    ...(op.opType === 'create' ? {} : { 'If-Match': `"${op.expectedVersion ?? 0}"` }),
  }
}

export function createCrudAdapter(config: Config): ModuleSyncAdapter {
  const itemUrl = config.item ?? ((id: number) => `${config.collection}/${id}`)
  return {
    module: config.module,
    mapServer: config.mapServer,
    async getServerData(op) {
      const fetch = scopedApiFetch()
      try {
        return await fetch<ServerEntity>(`/api/sync/${config.module}/${op.serverId}`)
      } catch (error) {
        if ((error as { status?: number }).status === 404) return { __deleted: true }
        throw error
      }
    },
    async pushCreate(op) {
      const fetch = scopedApiFetch()
      const requestHeaders = headers(op)
      await requireProtocol(fetch)
      const server = await fetch<ServerEntity>(config.createUrl?.(op) ?? config.collection, {
        method: 'POST', headers: requestHeaders, body: JSON.stringify(config.createBody(JSON.parse(op.payload))),
      })
      if (!serverVersion(server)) throw Object.assign(new Error('服务器未返回同步版本'), { status: 426 })
      return { server }
    },
    async pushUpdate(op) {
      const fetch = scopedApiFetch()
      const requestHeaders = headers(op)
      if (!op.serverId) throw new Error('前置创建尚未确认')
      await requireProtocol(fetch)
      const server = await fetch<ServerEntity>(itemUrl(op.serverId), {
        method: 'PUT', headers: requestHeaders, body: JSON.stringify(config.updateBody(JSON.parse(op.payload))),
      })
      if (!serverVersion(server)) throw Object.assign(new Error('服务器未返回同步版本'), { status: 426 })
      return { server }
    },
    async pushDelete(op) {
      const fetch = scopedApiFetch()
      const requestHeaders = headers(op)
      if (!op.serverId) throw new Error('前置创建尚未确认')
      await requireProtocol(fetch)
      try {
        await fetch(itemUrl(op.serverId), { method: 'DELETE', headers: requestHeaders })
      } catch (error) {
        if ((error as { status?: number }).status !== 404) throw error
      }
    },
    async pullAll() {
      const db = activeDb
      const fetch = scopedApiFetch()
      // Capture before fetching, not after: a stale full-list response must not
      // erase a row created or acknowledged while that request was in flight.
      const before = await db.table(config.module).toArray() as SyncMeta[]
      const beforeById = new Map(before.map(row => [row._localId, row]))
      const servers = config.list ? await config.list(fetch, db) : await fetch<ServerEntity[]>(config.collection)
      const serverIds = new Set(servers.map(server => server.id))
      await db.transaction('rw', db.tables, async () => {
        const table = db.table(config.module)
        const rows = await table.toArray() as SyncMeta[]
        const byServer = new Map(rows.filter(row => row._serverId != null).map(row => [row._serverId, row]))
        const queued = await db.opQueue.where('module').equals(config.module).toArray()
        const dirtyIds = new Set(queued.map(op => op.localId))
        const unknownCreates = queued.some(op => op.opType === 'create' && (op.claimedAt || op.legacyUncertain))
        const unchanged = (row: SyncMeta) => {
          const old = beforeById.get(row._localId)
          return old && old._syncStatus === 'synced' && row._syncStatus === 'synced' && !dirtyIds.has(row._localId)
            && old._localRevision === row._localRevision && old._serverVersion === row._serverVersion
            && old._updatedAt === row._updatedAt
        }
        for (const server of servers) {
          const local = byServer.get(server.id)
          const fields = config.mapServer(server)
          if (config.module === 'goalTasks') {
            const goal = await db.goals.where('_serverId').equals(server.goal_id as number).first()
            fields._localGoalId = goal?._localId ?? null
          }
          if (!local && !unknownCreates) {
            await table.add({
              ...fields, ...serverMeta(server), _localId: crypto.randomUUID(), _serverId: server.id,
              _localRevision: 0, _syncStatus: 'synced', _conflictAt: null, _conflictServerData: null,
            })
          } else if (local && unchanged(local) && (serverVersion(server) ?? 0) >= (local._serverVersion ?? 0)) {
            await table.update(local._localId, { ...fields, ...serverMeta(server) })
          }
          // Pending/failed/uncertain mutations are never inferred to conflict
          // from a pull; their own committed response may be the remote change.
        }
        if (config.completeSnapshot !== false) {
          for (const local of rows) {
            if (local._serverId != null && unchanged(local) && !serverIds.has(local._serverId)) await table.delete(local._localId)
          }
        }
      })
    },
  }
}
