import { db as activeDb, type ModuleName, type QueuedOperation } from '../db/studyDb'
import { isNetworkOnline } from '../services/apiClient'
import { claimOperation, deleteLocalGoalChildren } from './enqueueOperation'
import { acknowledgeOperation, serverMeta, serverVersion, type PushResult, type ServerEntity } from './syncProtocol'

// ── Adapter interface ──

export interface ModuleSyncAdapter {
  module: ModuleName
  pushCreate(op: QueuedOperation): Promise<PushResult | void>
  pushUpdate(op: QueuedOperation): Promise<PushResult | void>
  pushDelete(op: QueuedOperation): Promise<void>
  pullAll(): Promise<void>
  getServerData?(op: QueuedOperation): Promise<Record<string, unknown>>
  mapServer?(server: ServerEntity): Record<string, unknown>
}

// ── Sync status ──

export type SyncStatusValue = 'idle' | 'syncing' | 'offline' | 'error'

export interface SyncState {
  status: SyncStatusValue
  online: boolean
  failedCount: number
  conflictCount: number
  lastError?: string
}

interface SyncOptions {
  retryFailed?: boolean
}

type Listener = () => void

// ── SyncEngine ──

export class SyncEngine {
  private adapters = new Map<ModuleName, ModuleSyncAdapter>()
  private listeners = new Set<Listener>()
  private state: SyncState = { status: 'idle', online: navigator.onLine, failedCount: 0, conflictCount: 0 }
  private intervalId: ReturnType<typeof setInterval> | null = null
  private currentSyncPromise: Promise<void> | null = null
  private followUpRequested = false
  private authenticated = false
  private generation = 0
  private stopController = new AbortController()

  private isActive(generation: number): boolean {
    return this.authenticated && generation === this.generation
  }

  // ── Registration ──

  registerAdapter(adapter: ModuleSyncAdapter) {
    this.adapters.set(adapter.module, adapter)
  }

  // ── Lifecycle ──

  start(isAuthenticated = true) {
    this.authenticated = isAuthenticated
    if (!this.authenticated) {
      this.stop()
      return
    }
    if (this.intervalId) return
    this.stopController = new AbortController()
    window.addEventListener('online', this.handleOnline)
    window.addEventListener('offline', this.handleOffline)
    this.state.online = navigator.onLine
    if (!navigator.onLine) this.setState({ status: 'offline', online: false })

    if (this.intervalId) {
      return
    }

    // Periodic sync every 30 seconds
    this.intervalId = setInterval(() => {
      void this.syncAll()
    }, 30_000)

    // Initial sync
    void this.syncAll()
  }

  stop() {
    this.authenticated = false
    ++this.generation
    this.followUpRequested = false
    this.stopController.abort()
    window.removeEventListener('online', this.handleOnline)
    window.removeEventListener('offline', this.handleOffline)
    if (this.intervalId) {
      clearInterval(this.intervalId)
      this.intervalId = null
    }
    this.setState({ status: 'idle', online: navigator.onLine, failedCount: 0, conflictCount: 0, lastError: undefined })
  }

  // ── Public API ──

  async syncAll(options: SyncOptions = {}) {
    this.followUpRequested = true
    if (this.currentSyncPromise) {
      await this.currentSyncPromise
      return
    }
    const syncPromise = this.drainSyncRequests(options)
    this.currentSyncPromise = syncPromise
    try {
      await syncPromise
    } finally {
      if (this.currentSyncPromise === syncPromise) {
        this.currentSyncPromise = null
      }
    }
  }

  private async drainSyncRequests(options: SyncOptions) {
    let nextOptions = options
    do {
      this.followUpRequested = false
      await this.runSync(nextOptions)
      nextOptions = {}
    } while (this.followUpRequested)
  }

  private async runSync(options: SyncOptions = {}) {
    const generation = this.generation
    if (!this.authenticated) {
      this.setState({ status: 'idle', online: navigator.onLine, failedCount: 0, conflictCount: 0, lastError: undefined })
      return
    }
    // navigator describes connectivity; a previous backend outage must not disable probes forever.
    if (!navigator.onLine) {
      this.setState({ status: 'offline', online: false })
      return
    }

    this.setState({ status: 'syncing', online: true })

    try {
      const failedCount = await this.processQueue(options, generation)
      if (!this.isActive(generation)) return
      let pullFailed = false
      // Pull latest from server — each adapter is isolated so one failure won't block others
      for (const adapter of this.adapters.values()) {
        if (!this.isActive(generation)) return
        try {
          await adapter.pullAll()
        } catch (e) {
          pullFailed = true
          console.warn(`[SyncEngine] pullAll failed for module=${adapter.module}`, e)
        }
      }
      if (!this.isActive(generation)) return
      const conflictCount = await this.countConflicts()
      if (!this.isActive(generation)) return
      if (pullFailed) {
        this.setState({ status: isNetworkOnline() ? 'error' : 'offline', online: isNetworkOnline(), failedCount, conflictCount, lastError: '云端数据拉取失败，将自动重试' })
      } else if (failedCount > 0) {
        this.setState({
          status: 'error',
          online: true,
          failedCount,
          conflictCount,
          lastError: `${failedCount} 个本地改动同步失败，点击重试`,
        })
      } else if (conflictCount > 0) {
        this.setState({
          status: 'idle',
          online: true,
          failedCount: 0,
          conflictCount,
          lastError: undefined,
        })
      } else {
        this.setState({ status: 'idle', online: true, failedCount: 0, conflictCount: 0, lastError: undefined })
      }
    } catch (e) {
      if (!this.isActive(generation)) return
      const message = this.formatError(e)
      if (!isNetworkOnline()) {
        this.setState({ status: 'offline', online: false, lastError: message })
      } else {
        this.setState({ status: 'error', online: this.state.online, lastError: message })
      }
    }
  }

  async retryFailed() {
    await this.syncAll({ retryFailed: true })
  }

  /**
   * Resolve a concurrent edit deliberately. "keep_local" re-queues the
   * current local record after acknowledging the server version; "use_server"
   * drops only the unsynced local edit and refreshes from the adapter.
   */
  async resolveConflict(module: ModuleName, localId: string, strategy: 'keep_local' | 'use_server'): Promise<void> {
    const db = activeDb
    const generation = this.generation
    if (!this.isActive(generation)) throw new Error('请先登录')
    const table = db.table(module)
    const record = await table.get(localId) as Record<string, unknown> | undefined
    if (!record || record._syncStatus !== 'conflicted') throw new Error('这条同步冲突已不存在，请刷新后重试')
    const adapter = this.adapters.get(module)
    if (!adapter) throw new Error(`未注册同步适配器: ${module}`)
    let remote = this.parseConflictServerData(record._conflictServerData)
    if (strategy === 'use_server') {
      if (!adapter.getServerData) throw new Error('无法取得云端版本')
      remote = await adapter.getServerData({
        module, localId, opType: 'update', payload: '{}', createdAt: '', serverId: record._serverId as number,
      })
    }
    if (!remote || !this.isActive(generation)) throw new Error('无法确认当前会话或云端版本，请重试')
    const server = remote as unknown as ServerEntity
    const deleted = remote.__deleted === true
    if (!deleted && !serverVersion(server)) throw new Error('云端版本未知，请先升级服务器并刷新冲突')
    await db.transaction('rw', db.tables, async () => {
      const current = await table.get(localId)
      if (!current || current._syncStatus !== 'conflicted' || current._conflictAt !== record._conflictAt
        || current._localRevision !== record._localRevision) throw new Error('冲突已变化，请刷新后重试')
      if (module === 'goals' && deleted && (strategy === 'use_server' || record._conflictOpType === 'delete')) {
        await deleteLocalGoalChildren(localId, Number(record._serverId), db)
      }
      await db.opQueue.where({ module, localId }).delete()
      if (strategy === 'use_server') {
        if (deleted) await table.delete(localId)
        else await table.update(localId, {
          ...adapter.mapServer?.(server), ...serverMeta(server), _syncStatus: 'synced',
          _conflictAt: null, _conflictServerData: null, _conflictOpType: null, _syncError: null, _syncFailedAt: null,
        })
        return
      }
      const wantsDelete = record._conflictOpType === 'delete'
      if (deleted && wantsDelete) { await table.delete(localId); return }
      const type = wantsDelete ? 'delete' : deleted ? 'create' : 'update'
      const now = new Date().toISOString()
      await table.update(localId, {
        _serverId: deleted ? null : record._serverId, _serverVersion: deleted ? null : server.sync_version,
        _syncStatus: type === 'delete' ? 'pending_delete' : type === 'create' ? 'pending_create' : 'pending_update',
        _updatedAt: now, _localRevision: Number(record._localRevision ?? 0) + 1,
        _conflictAt: null, _conflictServerData: null, _conflictOpType: null, _syncError: null, _syncFailedAt: null,
      })
      await db.opQueue.add({
        module, localId, opType: type, payload: JSON.stringify(record), createdAt: now,
        operationId: crypto.randomUUID(), claimedAt: null,
      })
    })
    if (!this.isActive(generation)) return
    await this.refreshConflictCount()
    if (strategy === 'keep_local' && this.isActive(generation)) await this.syncAll()
  }

  getSnapshot = (): SyncState => this.state

  subscribe(listener: Listener): () => void {
    this.listeners.add(listener)
    return () => this.listeners.delete(listener)
  }

  // ── Queue processing ──

  private async processQueue(options: SyncOptions, generation: number): Promise<number> {
    const db = activeDb
    const snapshot = await db.opQueue.orderBy('id').toArray()
    for (const row of snapshot) {
      if (!this.isActive(generation)) return 0
      let op = await db.opQueue.get(row.id!)
      if (!op || op.legacyUncertain || (op.failedAt && !options.retryFailed)) continue
      const adapter = this.adapters.get(op.module)
      if (!adapter) {
        await this.markOperationFailed(op, `未注册同步适配器: ${op.module}`, 0)
        continue
      }
      for (let attempt = 1; attempt <= 5; attempt++) {
        if (!this.isActive(generation)) return 0
        try {
          const claimed = await claimOperation(op.id!, db)
          if (!claimed) break // failed/conflicted predecessor or cancelled unsent work
          op = claimed
          if (!this.isActive(generation)) return 0
          let result: PushResult | void
          if (op.opType === 'create') result = await adapter.pushCreate(op)
          else if (op.opType === 'update') result = await adapter.pushUpdate(op)
          else result = await adapter.pushDelete(op)
          if (!this.isActive(generation)) return 0
          await acknowledgeOperation(op, result, adapter.mapServer, db)
          break
        } catch (error) {
          if (!this.isActive(generation)) return 0
          const { status, code } = error as { status?: number; code?: string }
          if (code === 'SYNC_CONFLICT' || status === 412 || (status === 404 && op.opType === 'update')) {
            // Keep the immutable operation and all later intent until the user
            // explicitly chooses. A failed preview fetch must not discard either.
            try {
              const remote = await adapter.getServerData?.(op)
              if (!remote) throw new Error('无法取得云端冲突版本，请重试')
              if (!this.isActive(generation)) return 0
              await this.markOperationConflicted(op, remote)
            } catch (previewError) {
              if (!this.isActive(generation)) return 0
              await this.markOperationFailed(op, this.formatError(previewError), attempt)
            }
            break
          }
          if (!isNetworkOnline()) throw error
          if (attempt === 5 || (status !== undefined && status >= 400 && status < 500 && status !== 429)) {
            await this.markOperationFailed(op, this.formatError(error), attempt)
            break
          }
          await this.waitForRetry(Math.min(1000 * 2 ** (attempt - 1), 60_000))
        }
      }
    }
    return (await db.opQueue.toArray()).filter(op => op.failedAt || op.legacyUncertain).length
  }

  private async markOperationFailed(op: QueuedOperation, message: string, attempts: number) {
    const db = activeDb
    await db.transaction('rw', db.table(op.module), db.opQueue, async () => {
      const current = await db.opQueue.get(op.id!)
      if (!current || current.operationId !== op.operationId) return
      const failedAt = new Date().toISOString()
      await db.opQueue.update(op.id!, { attempts: (current.attempts || 0) + attempts, lastError: message, failedAt })
      const table = db.table(op.module)
      const local = await table.get(op.localId)
      if (local) await table.update(op.localId, {
        _syncStatus: ['pending_delete', 'conflicted'].includes(local._syncStatus) ? local._syncStatus : 'sync_failed',
        _syncError: message, _syncFailedAt: failedAt,
      })
    })
  }

  private async markOperationConflicted(op: QueuedOperation, serverData: unknown) {
    const db = activeDb
    await db.transaction('rw', db.table(op.module), db.opQueue, async () => {
      const current = await db.opQueue.get(op.id!)
      if (!current || current.operationId !== op.operationId) return
      const all = await db.opQueue.where({ module: op.module, localId: op.localId }).sortBy('id')
      await db.table(op.module).update(op.localId, {
        _conflictAt: new Date().toISOString(), _conflictServerData: JSON.stringify(serverData),
        _conflictOpType: all[all.length - 1]?.opType ?? op.opType,
        _syncStatus: 'conflicted', _syncError: null, _syncFailedAt: null,
      })
    })
  }

  private formatError(error: unknown): string {
    if (error instanceof Error) return error.message
    if (typeof error === 'string') return error
    return '同步失败'
  }

  private parseConflictServerData(value: unknown): Record<string, unknown> | null {
    if (typeof value !== 'string' || !value) return null
    try {
      const parsed = JSON.parse(value)
      return parsed && typeof parsed === 'object' ? parsed as Record<string, unknown> : null
    } catch {
      return null
    }
  }

  private async countConflicts(): Promise<number> {
    const db = activeDb
    let count = 0
    const modules: ModuleName[] = ['notes', 'goals', 'goalTasks', 'ankiCards', 'wrongQuestions']
    for (const module of modules) {
      const table = db.table?.(module)
      // The isolated engine test intentionally supplies only the queue mock.
      if (!table?.toArray) continue
      const rows = await table.toArray() as Array<{ _syncStatus?: string }>
      count += rows.filter((row) => row._syncStatus === 'conflicted').length
    }
    return count
  }

  private async refreshConflictCount() {
    this.setState({ conflictCount: await this.countConflicts() })
  }

  private waitForRetry(delay: number): Promise<void> {
    const signal = this.stopController.signal
    return new Promise((resolve) => {
      const finish = () => {
        clearTimeout(timer)
        signal.removeEventListener('abort', finish)
        resolve()
      }
      const timer = setTimeout(finish, delay)
      signal.addEventListener('abort', finish, { once: true })
      if (signal.aborted) finish()
    })
  }

  // ── Internal ──

  private handleOnline = () => {
    this.setState({ status: 'idle', online: true })
    if (this.authenticated) {
      void this.syncAll()
    }
  }

  private handleOffline = () => {
    this.setState({ status: 'offline', online: false })
  }

  private setState(next: Partial<SyncState>) {
    const prev = this.state
    this.state = { ...prev, ...next }
    if (
      prev.status !== this.state.status ||
      prev.online !== this.state.online ||
      prev.failedCount !== this.state.failedCount ||
      prev.conflictCount !== this.state.conflictCount ||
      prev.lastError !== this.state.lastError
    ) {
      this.listeners.forEach((l) => l())
    }
  }
}

export const syncEngine = new SyncEngine()
