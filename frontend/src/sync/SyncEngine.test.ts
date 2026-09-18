import 'fake-indexeddb/auto'
import Dexie from 'dexie'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
vi.mock('antd', () => ({ message: { error: vi.fn(), warning: vi.fn() } }))
import { db, openStudyDatabase, closeStudyDatabase } from '../db/studyDb'
import { setApiSessionUser } from '../services/sessionScope'
import { SyncEngine } from './SyncEngine'
import { enqueueOperation } from './enqueueOperation'

let engine: SyncEngine
const local = (id: string) => ({
  _localId: id, _serverId: 42, _serverVersion: 1, _syncStatus: 'pending_update',
  _updatedAt: '2026-09-12T12:00:00Z', title: '本机修改', content: '保留内容',
})
beforeEach(async () => {
  await openStudyDatabase({ id: 991, created_at: '2026-09-12T00:00:00Z' })
  setApiSessionUser(991)
  window.dispatchEvent(new Event('online'))
  engine = new SyncEngine()
})
afterEach(async () => {
  engine.stop(); setApiSessionUser(null); closeStudyDatabase()
  for (const name of await Dexie.getDatabaseNames()) await Dexie.delete(name)
  vi.restoreAllMocks()
})

describe('SyncEngine', () => {
  it('drains a follow-up request made during an active queue pass', async () => {
    await db.table('notes').put(local('first'))
    await enqueueOperation('notes', 'delete', 'first')
    let release!: () => void
    let started!: () => void
    const ready = new Promise<void>(resolve => { started = resolve })
    const wait = new Promise<void>(resolve => { release = resolve })
    const adapter = {
      module: 'notes' as const, pullAll: vi.fn(async () => {}),
      pushCreate: vi.fn(async () => {}), pushUpdate: vi.fn(async () => {}),
      pushDelete: vi.fn(async () => { started(); await wait }),
    }
    engine.registerAdapter(adapter); engine.start(); await ready
    await db.table('notes').put(local('second'))
    await enqueueOperation('notes', 'delete', 'second')
    const followUp = engine.syncAll(); release(); await followUp
    expect(adapter.pushDelete).toHaveBeenCalledTimes(2)
    expect(adapter.pullAll).toHaveBeenCalledTimes(2)
    expect(await db.opQueue.count()).toBe(0)
  })

  it('keeps the queue and both versions on a server CAS conflict', async () => {
    await db.table('notes').put(local('first'))
    await enqueueOperation('notes', 'update', 'first', { title: '本机修改' })
    const adapter = {
      module: 'notes' as const, pullAll: vi.fn(async () => {}),
      pushCreate: vi.fn(async () => {}), pushDelete: vi.fn(async () => {}),
      pushUpdate: vi.fn(async () => { throw Object.assign(new Error('资源已变化'), { status: 409, code: 'SYNC_CONFLICT' }) }),
      getServerData: vi.fn(async () => ({ id: 42, sync_version: 2, title: '云端修改' })),
    }
    engine.registerAdapter(adapter); engine.start(); await engine.syncAll()
    expect(adapter.pushUpdate).toHaveBeenCalledTimes(1)
    const record = await db.notes.get('first')
    expect(record?._syncStatus).toBe('conflicted')
    expect(record?.title).toBe('本机修改')
    expect(record?._conflictServerData).toContain('云端修改')
    expect(await db.opQueue.count()).toBe(1)
    expect(engine.getSnapshot().conflictCount).toBe(1)
  })
})
