import { db, type ModuleName, type QueuedOperation } from '../db/studyDb'
import { isNetworkOnline } from '../services/apiClient'

// ── Adapter interface ──

export interface ModuleSyncAdapter {
  module: ModuleName
  pushCreate(op: QueuedOperation): Promise<void>
  pushUpdate(op: QueuedOperation): Promise<void>
  pushDelete(op: QueuedOperation): Promise<void>
  pullAll(): Promise<void>
  /**
   * 可选：检测服务端是否在本地上次同步后修改过该记录。
   * 返回 true 表示有冲突，应跳过本次 push 并标记冲突。
   */
  checkConflict?(op: QueuedOperation): Promise<{ conflict: boolean; serverData?: unknown }>
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
    if (!this.authenticated) {
      this.setState({ status: 'idle', online: navigator.onLine, failedCount: 0, conflictCount: 0, lastError: undefined })
      return
    }
    if (!isNetworkOnline()) {
      this.setState({ status: 'offline', online: false })
      return
    }

    this.setState({ status: 'syncing', online: true })

    try {
      const failedCount = await this.processQueue(options)
      // Pull latest from server — each adapter is isolated so one failure won't block others
      for (const adapter of this.adapters.values()) {
        try {
          await adapter.pullAll()
        } catch (e) {
          console.warn(`[SyncEngine] pullAll failed for module=${adapter.module}`, e)
        }
      }
      const conflictCount = await this.countConflicts()
      if (failedCount > 0) {
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
      const message = this.formatError(e)
      if (!isNetworkOnline()) {
        this.setState({ status: 'offline', online: false, lastError: message })
      } else {
        this.setState({ status: 'error', online: this.state.online, lastError: message })
      }
    } finally {
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
  async resolveConflict(
    module: ModuleName,
    localId: string,
    strategy: 'keep_local' | 'use_server',
  ): Promise<void> {
    const table = db.table(module)
    const record = await table.get(localId) as Record<string, unknown> | undefined
    if (!record || record._syncStatus !== 'conflicted') {
      throw new Error('这条同步冲突已不存在，请刷新后重试')
    }

    if (strategy === 'keep_local') {
      const now = new Date().toISOString()
      const remote = this.parseConflictServerData(record._conflictServerData)
      const serverUpdatedAt = typeof remote?.updated_at === 'string' ? remote.updated_at : null
      const serverDeleted = remote?.__deleted === true
      await db.opQueue.where({ module, localId }).delete()
      await table.update(localId, {
        _syncStatus: 'pending_update',
        _updatedAt: now,
        // The learner has now seen the remote version. Save its revision as
        // the new comparison point so the confirmed local choice can be sent.
        _lastSyncedAt: serverUpdatedAt ?? record._lastSyncedAt ?? now,
        _conflictAt: null,
        _conflictServerData: null,
        _syncError: null,
        _syncFailedAt: null,
      })
      await db.opQueue.add({
        module,
        // A confirmed local choice can recreate an item deleted elsewhere;
        // this is still explicit user intent, never an automatic resurrection.
        opType: serverDeleted ? 'create' : 'update',
        localId,
        payload: JSON.stringify(record),
        createdAt: now,
      })
      await this.refreshConflictCount()
      await this.syncAll()
      return
    }

    await db.opQueue.where({ module, localId }).delete()
    await table.update(localId, {
      _syncStatus: 'synced',
      _conflictAt: null,
      _conflictServerData: null,
      _syncError: null,
      _syncFailedAt: null,
    })
    const adapter = this.adapters.get(module)
    if (!adapter) throw new Error(`未注册同步适配器: ${module}`)
    await adapter.pullAll()
    await this.refreshConflictCount()
  }

  getSnapshot = (): SyncState => this.state

  subscribe(listener: Listener): () => void {
    this.listeners.add(listener)
    return () => this.listeners.delete(listener)
  }

  // ── Queue processing ──

  private async processQueue(options: SyncOptions = {}): Promise<number> {
    const ops = await db.opQueue.orderBy('id').toArray()
    const MAX_RETRIES = 5
    let retryDelay = 1000
    const MAX_DELAY = 60_000
    let failedCount = options.retryFailed ? 0 : ops.filter((op) => op.failedAt).length

    for (const op of ops) {
      if (op.failedAt && !options.retryFailed) {
        continue
      }

      const adapter = this.adapters.get(op.module)
      if (!adapter) {
        await this.markOperationFailed(op, `未注册同步适配器: ${op.module}`, 0)
        failedCount++
        continue
      }

      let success = false
      let attempts = 0
      let lastError = op.lastError || ''
      while (!success && attempts < MAX_RETRIES) {
        try {
          // 冲突检测：对 update 操作检查服务端是否已被修改
          if (op.opType === 'update' && adapter.checkConflict) {
            const conflictResult = await adapter.checkConflict(op)
            if (conflictResult.conflict) {
              console.warn(`[SyncEngine] Conflict detected for op ${op.id}, marking conflict`)
              // Do not overwrite either copy.  The explicit state leaves the
              // final choice to the learner instead of silently using a clock.
              await this.markOperationConflicted(op, conflictResult.serverData)
              await db.opQueue.delete(op.id!)
              success = true // 不算失败，而是已处理
              break
            }
          }
          switch (op.opType) {
            case 'create':
              await adapter.pushCreate(op)
              break
            case 'update':
              await adapter.pushUpdate(op)
              break
            case 'delete':
              await adapter.pushDelete(op)
              break
          }
          success = true
          await this.clearOperationFailure(op)
          await db.opQueue.delete(op.id!)
          retryDelay = 1000 // reset on success
        } catch (e) {
          attempts++
          lastError = this.formatError(e)
          if (!isNetworkOnline()) {
            this.setState({ status: 'offline', online: false })
            throw e // stop processing, will resume when online
          }
          // Exponential backoff
          await new Promise((r) => setTimeout(r, retryDelay))
          retryDelay = Math.min(retryDelay * 2, MAX_DELAY)
        }
      }

      if (!success) {
        console.error(`[SyncEngine] Permanently failed op ${op.id} (module=${op.module}, type=${op.opType}) after ${MAX_RETRIES} attempts`, lastError)
        await this.markOperationFailed(op, lastError || '同步失败', attempts)
        failedCount++
      }
    }

    return failedCount
  }

  private async markOperationFailed(op: QueuedOperation, message: string, attempts: number) {
    const failedAt = new Date().toISOString()
    await db.opQueue.update(op.id!, {
      attempts: (op.attempts || 0) + attempts,
      lastError: message,
      failedAt,
    })

    if (op.opType === 'delete') return

    try {
      const table = db.table(op.module)
      const record = await table.get(op.localId)
      if (record) {
        await table.update(op.localId, {
          _syncStatus: 'sync_failed',
          _syncError: message,
          _syncFailedAt: failedAt,
        })
      }
    } catch (e) {
      console.warn(`[SyncEngine] Failed to mark local record sync_failed for op ${op.id}`, e)
    }
  }

  private async markOperationConflicted(op: QueuedOperation, serverData: unknown) {
    const table = db.table(op.module)
    const record = await table.get(op.localId)
    if (!record) return
    await table.update(op.localId, {
      _conflictAt: new Date().toISOString(),
      _conflictServerData: JSON.stringify(serverData ?? null),
      _syncStatus: 'conflicted',
      _syncError: null,
      _syncFailedAt: null,
    })
  }

  private async clearOperationFailure(op: QueuedOperation) {
    if (op.opType === 'delete') return

    try {
      const table = db.table(op.module)
      const record = await table.get(op.localId)
      if (record) {
        await table.update(op.localId, {
          _syncError: null,
          _syncFailedAt: null,
        })
      }
    } catch (e) {
      console.warn(`[SyncEngine] Failed to clear local sync failure for op ${op.id}`, e)
    }
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
