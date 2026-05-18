import { db, type ModuleName, type QueuedOperation } from '../db/studyDb'
import { getToken, isNetworkOnline } from '../services/apiClient'

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
  lastError?: string
}

interface SyncOptions {
  retryFailed?: boolean
}

type Listener = () => void

// ── SyncEngine ──

class SyncEngine {
  private adapters = new Map<ModuleName, ModuleSyncAdapter>()
  private listeners = new Set<Listener>()
  private state: SyncState = { status: 'idle', online: navigator.onLine, failedCount: 0 }
  private intervalId: ReturnType<typeof setInterval> | null = null
  private processing = false
  private authenticated = false

  // ── Registration ──

  registerAdapter(adapter: ModuleSyncAdapter) {
    this.adapters.set(adapter.module, adapter)
  }

  // ── Lifecycle ──

  start(isAuthenticated = true) {
    this.authenticated = isAuthenticated && !!getToken()
    if (!this.authenticated) {
      this.stop()
      return
    }
    if (this.intervalId) return
    window.addEventListener('online', this.handleOnline)
    window.addEventListener('offline', this.handleOffline)
    this.state.online = navigator.onLine
    if (!navigator.onLine) this.setState({ status: 'offline', online: false })

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
    this.setState({ status: 'idle', online: navigator.onLine })
  }

  // ── Public API ──

  async syncAll(options: SyncOptions = {}) {
    if (this.processing) return
    if (!this.authenticated || !getToken()) {
      this.setState({ status: 'idle', online: navigator.onLine, failedCount: 0, lastError: undefined })
      return
    }
    if (!isNetworkOnline()) {
      this.setState({ status: 'offline', online: false })
      return
    }

    this.processing = true
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
      if (failedCount > 0) {
        this.setState({
          status: 'error',
          online: true,
          failedCount,
          lastError: `${failedCount} 个本地改动同步失败，点击重试`,
        })
      } else {
        this.setState({ status: 'idle', online: true, failedCount: 0, lastError: undefined })
      }
    } catch (e) {
      const message = this.formatError(e)
      if (!isNetworkOnline()) {
        this.setState({ status: 'offline', online: false, lastError: message })
      } else {
        this.setState({ status: 'error', online: this.state.online, lastError: message })
      }
    } finally {
      this.processing = false
    }
  }

  async retryFailed() {
    await this.syncAll({ retryFailed: true })
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
              // 标记冲突而非直接覆盖，让用户决定
              const table = db.table(op.module)
              const record = await table.get(op.localId)
              if (record) {
                await table.update(op.localId, {
                  _conflictAt: new Date().toISOString(),
                  _conflictServerData: JSON.stringify(conflictResult.serverData),
                  _syncStatus: 'pending_update', // 保持 pending 状态等待用户解决
                  _syncError: null,
                  _syncFailedAt: null,
                })
              }
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

  // ── Internal ──

  private handleOnline = () => {
    this.setState({ status: 'idle', online: true })
    if (this.authenticated && getToken()) {
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
      prev.lastError !== this.state.lastError
    ) {
      this.listeners.forEach((l) => l())
    }
  }
}

export const syncEngine = new SyncEngine()
