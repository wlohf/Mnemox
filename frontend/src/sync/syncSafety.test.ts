import 'fake-indexeddb/auto'
import Dexie from 'dexie'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
vi.mock('antd', () => ({ message: { error: vi.fn(), warning: vi.fn() } }))
import { db, openStudyDatabase, closeStudyDatabase, type QueuedOperation } from '../db/studyDb'
import { setApiSessionUser } from '../services/sessionScope'
import { SyncEngine } from './SyncEngine'
import { notesSyncAdapter } from './adapters/notesSyncAdapter'
import { ankiCardsSyncAdapter } from './adapters/ankiCardsSyncAdapter'
import { wrongQuestionsSyncAdapter } from './adapters/wrongQuestionsSyncAdapter'
import { goalTasksSyncAdapter } from './adapters/goalTasksSyncAdapter'
import { claimOperation } from './enqueueOperation'
import { acknowledgeOperation } from './syncProtocol'

const jsonResponse = (data: unknown) => new Response(JSON.stringify(data))
const withProtocol = (action: (url: string, options?: RequestInit) => Promise<Response>) =>
  vi.fn((url: string, options?: RequestInit) => url === '/api/sync/capabilities'
    ? Promise.resolve(jsonResponse({ protocol_version: 1 })) : action(url, options))

const alice = { id: 101, created_at: '2026-09-12T00:00:00Z' }
const bob = { id: 102, created_at: '2026-09-12T00:00:00Z' }
let engine: SyncEngine | undefined
const operation = (module: QueuedOperation['module'] = 'notes'): QueuedOperation => ({
  module, opType: 'delete', localId: 'local-1', payload: '{}', createdAt: new Date().toISOString(),
})
const record = () => ({
  _localId: 'local-1', _serverId: 42, _syncStatus: 'pending_delete', _updatedAt: new Date().toISOString(),
  _lastSyncedAt: null, title: 'private A', content: 'private content', tags: '[]', links: '[]',
})

beforeEach(async () => {
  setApiSessionUser(alice.id)
  await openStudyDatabase(alice)
  window.dispatchEvent(new Event('online'))
  vi.spyOn(console, 'warn').mockImplementation(() => {})
})
afterEach(async () => {
  engine?.stop(); engine = undefined
  setApiSessionUser(null)
  closeStudyDatabase()
  for (const name of await Dexie.getDatabaseNames()) await Dexie.delete(name)
  vi.unstubAllGlobals(); vi.restoreAllMocks()
})

describe('sync deletion and account safety', () => {
  for (const adapter of [notesSyncAdapter, ankiCardsSyncAdapter, wrongQuestionsSyncAdapter]) {
    it.each([403, 503])(`${adapter.module} retains delete intent on HTTP %i`, async (status) => {
      await db.table(adapter.module).put(record())
      const id = await db.opQueue.add(operation(adapter.module))
      const op = (await claimOperation(id))!
      vi.stubGlobal('fetch', withProtocol(async () => new Response('{"detail":"unavailable"}', { status })))
      await expect(adapter.pushDelete(op)).rejects.toMatchObject({ status })
      expect(await db.opQueue.get(id)).toBeDefined()
      expect(await db.table(adapter.module).get('local-1')).toBeDefined()
    })
    it(`${adapter.module} accepts only a confirmed missing remote record as deleted`, async () => {
      await db.table(adapter.module).put(record())
      const id = await db.opQueue.add(operation(adapter.module))
      const op = (await claimOperation(id))!
      vi.stubGlobal('fetch', withProtocol(async () => new Response('{"detail":"not found"}', { status: 404 })))
      await adapter.pushDelete(op)
      // Network adapters cannot acknowledge local rows outside the queue transaction.
      expect(await db.table(adapter.module).get('local-1')).toBeDefined()
      await acknowledgeOperation(op, undefined)
      expect(await db.table(adapter.module).get('local-1')).toBeUndefined()
    })
  }

  it('keeps both queue row and tombstone after a network delete failure', async () => {
    await db.table('notes').put(record())
    await db.opQueue.add(operation())
    vi.stubGlobal('fetch', vi.fn(async () => { throw new TypeError('network disconnected') }))
    engine = new SyncEngine(); engine.registerAdapter(notesSyncAdapter)
    engine.start(); await engine.syncAll()
    expect(await db.opQueue.count()).toBe(1)
    expect((await db.notes.get('local-1'))?._syncStatus).toBe('pending_delete')
    expect(engine.getSnapshot().status).toBe('offline')
    // Backend recovery needs no browser offline/online transition.
    vi.stubGlobal('fetch', withProtocol(async (_url: string, options?: RequestInit) => options?.method === 'DELETE'
      ? new Response('{"ok":true}') : new Response('[]')))
    await engine.syncAll()
    expect(await db.opQueue.count()).toBe(0)
    expect(engine.getSnapshot().status).toBe('idle')
  })

  it('never pushes A pending creates when B logs in', async () => {
    await db.table('notes').put({ ...record(), _serverId: null, _syncStatus: 'pending_create' })
    await db.opQueue.add({ ...operation(), opType: 'create', payload: JSON.stringify(record()) })
    closeStudyDatabase(); setApiSessionUser(bob.id); await openStudyDatabase(bob)
    const request = vi.fn(async () => new Response('[]'))
    vi.stubGlobal('fetch', request)
    engine = new SyncEngine(); engine.registerAdapter(notesSyncAdapter)
    engine.start(); await engine.syncAll(); engine.stop()
    expect(request.mock.calls.every((call) => !(call as unknown as [string, RequestInit])[1]?.method)).toBe(true)
    expect(await db.notes.count()).toBe(0)
    setApiSessionUser(alice.id); await openStudyDatabase(alice)
    expect(await db.opQueue.count()).toBe(1)
  })

  it('discards a late A pull instead of writing its private records into B database', async () => {
    let finish!: (response: Response) => void
    let started!: () => void
    const ready = new Promise<void>((resolve) => { started = resolve })
    vi.stubGlobal('fetch', vi.fn(() => new Promise<Response>((resolve) => { finish = resolve; started() })))
    engine = new SyncEngine(); engine.registerAdapter(notesSyncAdapter)
    engine.start(); await ready
    const running = engine.syncAll()
    engine.stop(); setApiSessionUser(bob.id); await openStudyDatabase(bob)
    await db.opQueue.add({ ...operation(), payload: 'B intent' })
    finish(new Response('[{"id":42,"title":"private A","content":"secret"}]'))
    await running
    expect(await db.notes.count()).toBe(0)
    expect((await db.opQueue.toArray())[0].payload).toBe('B intent')
  })

  it('never interprets a partially failed goal task pull as remote deletions', async () => {
    await db.table('goals').put({ ...record(), _syncStatus: 'synced', _serverId: 7 })
    await db.table('goalTasks').put({ ...record(), _syncStatus: 'synced', goal_id: 7 })
    vi.stubGlobal('fetch', vi.fn(async () => new Response('{"detail":"unavailable"}', { status: 503 })))
    await expect(goalTasksSyncAdapter.pullAll()).rejects.toMatchObject({ status: 503 })
    expect(await db.goalTasks.count()).toBe(1)
  })
})
