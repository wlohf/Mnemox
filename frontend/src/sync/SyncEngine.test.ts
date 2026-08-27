import { afterEach, describe, expect, it, vi } from 'vitest'

const syncMocks = vi.hoisted(() => {
  const queueReads: Array<Array<Record<string, unknown>>> = []
  return {
    deleteOperation: vi.fn(),
    getQueueRows: vi.fn(async () => queueReads.shift() ?? []),
    isNetworkOnline: vi.fn(() => true),
    queueReads,
    table: vi.fn(),
    token: vi.fn(() => 'test-token'),
  }
})

vi.mock('../db/studyDb', () => ({
  db: {
    opQueue: {
      orderBy: vi.fn(() => ({ toArray: syncMocks.getQueueRows })),
      delete: syncMocks.deleteOperation,
    },
    table: syncMocks.table,
  },
}))

vi.mock('../services/apiClient', () => ({
  getToken: syncMocks.token,
  isNetworkOnline: syncMocks.isNetworkOnline,
}))

import { SyncEngine } from './SyncEngine'

describe('SyncEngine', () => {
  afterEach(() => {
    syncMocks.queueReads.length = 0
    vi.clearAllMocks()
  })

  it('drains a follow-up sync request made during an active queue pass', async () => {
    let releaseDelete: (() => void) | undefined
    let markDeleteStarted: (() => void) | undefined
    const deleteStarted = new Promise<void>((resolve) => {
      markDeleteStarted = resolve
    })
    const delayedDelete = new Promise<void>((resolve) => {
      releaseDelete = resolve
    })
    syncMocks.queueReads.push(
      [{
        id: 1,
        module: 'notes',
        opType: 'delete',
        localId: 'note-1',
        payload: '{}',
        attempts: 0,
        failedAt: null,
        lastError: null,
      }],
      [],
    )

    const engine = new SyncEngine()
    const adapter = {
      module: 'notes' as const,
      pullAll: vi.fn(async () => undefined),
      pushCreate: vi.fn(async () => undefined),
      pushUpdate: vi.fn(async () => undefined),
      pushDelete: vi.fn(async () => {
        markDeleteStarted?.()
        await delayedDelete
      }),
    }
    engine.registerAdapter(adapter)

    engine.start()
    await deleteStarted
    const followUpSync = engine.syncAll()
    releaseDelete?.()
    await followUpSync

    expect(syncMocks.getQueueRows).toHaveBeenCalledTimes(2)
    expect(adapter.pullAll).toHaveBeenCalledTimes(2)
    engine.stop()
  })

  it('stops a concurrent update for an explicit learner decision instead of overwriting it', async () => {
    const localRecord: Record<string, unknown> = {
      _localId: 'note-1',
      _syncStatus: 'pending_update',
      _lastSyncedAt: '2026-08-27T08:00:00.000Z',
      title: '本机修改',
    }
    const localTable = {
      get: vi.fn(async () => localRecord),
      update: vi.fn(async (_id: string, patch: Record<string, unknown>) => Object.assign(localRecord, patch)),
      toArray: vi.fn(async () => [localRecord]),
    }
    const emptyTable = { toArray: vi.fn(async () => []) }
    syncMocks.table.mockImplementation((module: string) => module === 'notes' ? localTable : emptyTable)
    syncMocks.queueReads.push([
      {
        id: 1,
        module: 'notes',
        opType: 'update',
        localId: 'note-1',
        payload: JSON.stringify({ title: '本机修改' }),
        attempts: 0,
        failedAt: null,
        lastError: null,
      },
    ])

    let resolvePull: (() => void) | undefined
    const pulled = new Promise<void>((resolve) => { resolvePull = resolve })
    const engine = new SyncEngine()
    const adapter = {
      module: 'notes' as const,
      pullAll: vi.fn(async () => resolvePull?.()),
      pushCreate: vi.fn(async () => undefined),
      pushUpdate: vi.fn(async () => undefined),
      pushDelete: vi.fn(async () => undefined),
      checkConflict: vi.fn(async () => ({
        conflict: true,
        serverData: { title: '云端修改', updated_at: '2026-08-27T09:00:00.000Z' },
      })),
    }
    engine.registerAdapter(adapter)

    engine.start()
    await pulled
    // Wait for the active pass to publish its conflict count. Calling syncAll
    // during that pass exercises the normal coalescing path as well.
    await engine.syncAll()

    expect(adapter.pushUpdate).not.toHaveBeenCalled()
    expect(localRecord._syncStatus).toBe('conflicted')
    expect(localRecord._conflictServerData).toContain('云端修改')
    expect(syncMocks.deleteOperation).toHaveBeenCalledWith(1)
    expect(engine.getSnapshot().conflictCount).toBe(1)
    engine.stop()
  })
})
