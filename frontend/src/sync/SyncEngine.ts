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
}

type Listener = () => void

// ── SyncEngine ──

class SyncEngine {
  private adapters = new Map<ModuleName, ModuleSyncAdapter>()
  private listeners = new Set<Listener>()
  private state: SyncState = { status: 'idle', online: navigator.onLine }
  private intervalId: ReturnType<typeof setInterval> | null = null
  private processing = false

  // ── Registration ──

  registerAdapter(adapter: ModuleSyncAdapter) {
    this.adapters.set(adapter.module, adapter)
  }

  // ── Lifecycle ──

  start() {
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
    window.removeEventListener('online', this.handleOnline)
    window.removeEventListener('offline', this.handleOffline)
    if (this.intervalId) {
      clearInterval(this.intervalId)
      this.intervalId = null
    }
  }

  // ── Public API ──

  async syncAll() {
    if (this.processing) return
    if (!isNetworkOnline()) {
      this.setState({ status: 'offline', online: false })
      return
    }

    this.processing = true
    this.setState({ status: 'syncing', online: true })

    try {
      await this.processQueue()
      // Pull latest from server — each adapter is isolated so one failure won't block others
      for (const adapter of this.adapters.values()) {
        try {
          await adapter.pullAll()
        } catch (e) {
          console.warn(`[SyncEngine] pullAll failed for module=${adapter.module}`, e)
        }
      }
      this.setState({ status: 'idle', online: true })
    } catch {
      this.setState({ status: 'error', online: this.state.online })
    } finally {
      this.processing = false
    }
  }

  getSnapshot = (): SyncState => this.state

  subscribe(listener: Listener): () => void {
    this.listeners.add(listener)
    return () => this.listeners.delete(listener)
  }

  // ── Queue processing ──

  private async processQueue() {
    const ops = await db.opQueue.orderBy('id').toArray()
    const MAX_RETRIES = 5
    let retryDelay = 1000
    const MAX_DELAY = 60_000

    for (const op of ops) {
      const adapter = this.adapters.get(op.module)
      if (!adapter) {
        // No adapter registered for this module, skip
        await db.opQueue.delete(op.id!)
        continue
      }

      let success = false
      let attempts = 0
      while (!success && attempts < 5) {
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
          await db.opQueue.delete(op.id!)
          retryDelay = 1000 // reset on success
        } catch {
          attempts++
          if (!isNetworkOnline()) {
            this.setState({ status: 'offline', online: false })
            return // stop processing, will resume when online
          }
          // Exponential backoff
          await new Promise((r) => setTimeout(r, retryDelay))
          retryDelay = Math.min(retryDelay * 2, MAX_DELAY)
        }
      }

      if (!success) {
        // 永久失败：从队列中移除，避免无限重试
        console.error(`[SyncEngine] Permanently failed op ${op.id} (module=${op.module}, type=${op.opType}) after ${MAX_RETRIES} attempts, removing from queue`)
        await db.opQueue.delete(op.id!)
      }
    }
  }

  // ── Internal ──

  private handleOnline = () => {
    this.setState({ status: 'idle', online: true })
    void this.syncAll()
  }

  private handleOffline = () => {
    this.setState({ status: 'offline', online: false })
  }

  private setState(next: Partial<SyncState>) {
    const prev = this.state
    this.state = { ...prev, ...next }
    if (prev.status !== this.state.status || prev.online !== this.state.online) {
      this.listeners.forEach((l) => l())
    }
  }
}

export const syncEngine = new SyncEngine()
