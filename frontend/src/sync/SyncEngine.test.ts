import { afterEach, describe, expect, it, vi } from 'vitest'

const syncMocks = vi.hoisted(() => {
  const queueReads: Array<Array<Record<string, unknown>>> = []
  return {
    deleteOperation: vi.fn(),
    getQueueRows: vi.fn(async () => queueReads.shift() ?? []),
    isNetworkOnline: vi.fn(() => true),
    queueReads,
    token: vi.fn(() => 'test-token'),
  }
})

vi.mock('../db/studyDb', () => ({
  db: {
    opQueue: {
      orderBy: vi.fn(() => ({ toArray: syncMocks.getQueueRows })),
      delete: syncMocks.deleteOperation,
    },
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
    engine.start()
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

    const firstSync = engine.syncAll()
    await deleteStarted
    const followUpSync = engine.syncAll()
    releaseDelete?.()
    await Promise.all([firstSync, followUpSync])

    expect(syncMocks.getQueueRows).toHaveBeenCalledTimes(2)
    expect(adapter.pullAll).toHaveBeenCalledTimes(2)
    engine.stop()
  })
})
