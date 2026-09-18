import 'fake-indexeddb/auto'
import Dexie from 'dexie'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
vi.mock('antd', () => ({ message: { error: vi.fn(), warning: vi.fn() } }))
import { db, closeStudyDatabase, openStudyDatabase, studyDatabaseName, type LocalNote } from '../db/studyDb'
import { setApiSessionUser } from '../services/sessionScope'
import { saveLocalOperation, claimOperation } from './enqueueOperation'
import { acknowledgeOperation, utcTimestamp } from './syncProtocol'
import { SyncEngine } from './SyncEngine'
import { notesSyncAdapter } from './adapters/notesSyncAdapter'
import { goalsSyncAdapter } from './adapters/goalsSyncAdapter'
import { ankiCardsSyncAdapter } from './adapters/ankiCardsSyncAdapter'
import { wrongQuestionsSyncAdapter } from './adapters/wrongQuestionsSyncAdapter'

const user = { id: 801, created_at: '2026-09-12T00:00:00Z' }
const now = '2026-09-12T12:00:00.000Z'
const note = (overrides: Partial<LocalNote> = {}): LocalNote => ({
  _localId: 'n1', _serverId: 42, _serverVersion: 1, _localRevision: 0, _syncStatus: 'synced',
  _updatedAt: now, _lastSyncedAt: now, _conflictAt: null, _conflictServerData: null,
  title: 'base', content: 'private content', note_type: 'general', tags: '[]', links: '[]',
  material_id: null, chapter_id: null, created_at: now, ...overrides,
})
const serverNote = (title = 'base', sync_version = 1) => ({ id: 42, title, content: 'private content', sync_version, updated_at: now, created_at: now })
const response = (body: unknown) => new Response(JSON.stringify(body))
let engine: SyncEngine | undefined
beforeEach(async () => {
  await openStudyDatabase(user); setApiSessionUser(user.id)
  window.dispatchEvent(new Event('online'))
  vi.spyOn(console, 'warn').mockImplementation(() => {})
})
afterEach(async () => {
  engine?.stop(); engine = undefined; setApiSessionUser(null); closeStudyDatabase()
  vi.restoreAllMocks(); vi.unstubAllGlobals()
  for (const name of await Dexie.getDatabaseNames()) await Dexie.delete(name)
})
async function firstClaim() { return (await claimOperation((await db.opQueue.orderBy('id').first())!.id!))! }

describe('atomic and immutable local operations', () => {
  it('rolls the local edit back when insertion into the queue fails', async () => {
    await db.notes.put(note())
    vi.spyOn(db.opQueue, 'add').mockRejectedValueOnce(new Error('quota exceeded'))
    await expect(saveLocalOperation('notes', 'update', 'n1', { title: 'lost?' })).rejects.toThrow('quota exceeded')
    expect((await db.notes.get('n1'))?.title).toBe('base')
    expect(await db.opQueue.count()).toBe(0)
  })
  it('acknowledges only the claimed edit, retaining equal-clock subsequent edits', async () => {
    await db.notes.put(note())
    await saveLocalOperation('notes', 'update', 'n1', { title: 'first' })
    const first = await firstClaim()
    await saveLocalOperation('notes', 'update', 'n1', { title: 'second' })
    expect((await db.opQueue.get(first.id!))?.payload).toBe(first.payload)
    await acknowledgeOperation(first, { server: serverNote('first', 2) }, notesSyncAdapter.mapServer)
    expect(await db.notes.get('n1')).toMatchObject({ title: 'second', _syncStatus: 'pending_update', _serverVersion: 2 })
    const next = await firstClaim()
    expect(next.operationId).not.toBe(first.operationId)
    expect(next.expectedVersion).toBe(2)
    // A late duplicate acknowledgement must not touch the newer operation.
    await acknowledgeOperation(first, { server: serverNote('first', 2) }, notesSyncAdapter.mapServer)
    expect(await db.opQueue.count()).toBe(1)
    expect((await db.notes.get('n1'))?.title).toBe('second')
  })
  it('preserves a delete made during a push until its own acknowledgement', async () => {
    await db.notes.put(note())
    await saveLocalOperation('notes', 'update', 'n1', { title: 'first' })
    const first = await firstClaim()
    await saveLocalOperation('notes', 'delete', 'n1')
    await acknowledgeOperation(first, { server: serverNote('first', 2) }, notesSyncAdapter.mapServer)
    expect((await db.notes.get('n1'))?._syncStatus).toBe('pending_delete')
    const deletion = await firstClaim()
    expect(deletion).toMatchObject({ opType: 'delete', expectedVersion: 2, serverId: 42 })
    await acknowledgeOperation(deletion, undefined)
    expect(await db.notes.get('n1')).toBeUndefined()
    expect(await db.opQueue.count()).toBe(0)
  })
  it('cancels only definitely unsent creates', async () => {
    await saveLocalOperation('notes', 'create', 'n1', note({ _serverId: null }))
    await saveLocalOperation('notes', 'update', 'n1', { title: 'updated before send' })
    await saveLocalOperation('notes', 'delete', 'n1')
    expect(await db.opQueue.count()).toBe(0)
    expect(await db.notes.count()).toBe(0)
  })
  it('does not let later operations overtake a failed immutable predecessor', async () => {
    await db.notes.put(note())
    await saveLocalOperation('notes', 'update', 'n1', { title: 'first' })
    const first = await firstClaim()
    await saveLocalOperation('notes', 'update', 'n1', { title: 'second' })
    const rows = await db.opQueue.orderBy('id').toArray()
    await db.opQueue.update(first.id!, { failedAt: now })
    expect(await claimOperation(rows[1].id!)).toBeUndefined()
    expect(await claimOperation(first.id!)).toEqual({ ...first, failedAt: now })
  })
  it('serializes two local writers without losing disjoint fields', async () => {
    await db.notes.put(note())
    await Promise.all([
      saveLocalOperation('notes', 'update', 'n1', { title: 'new title' }),
      saveLocalOperation('notes', 'update', 'n1', { content: 'new content' }),
    ])
    expect(await db.notes.get('n1')).toMatchObject({ title: 'new title', content: 'new content', _localRevision: 2 })
    expect(JSON.parse((await db.opQueue.toArray())[0].payload)).toMatchObject({ title: 'new title', content: 'new content' })
  })
})

describe('goal deletion intent', () => {
  it('cancels local child operations when an unsent goal is deleted', async () => {
    await saveLocalOperation('goals', 'create', 'g1', { ...note(), _localId: 'g1', status: 'active' })
    await saveLocalOperation('goalTasks', 'create', 't1', { ...note(), _localId: 't1', _localGoalId: 'g1', goal_id: null })
    await saveLocalOperation('goals', 'delete', 'g1')
    expect(await db.goals.count()).toBe(0)
    expect(await db.goalTasks.count()).toBe(0)
    expect(await db.opQueue.count()).toBe(0)
  })
  it('only removes children after a remote goal deletion is acknowledged', async () => {
    await db.table('goals').put({ ...note(), _localId: 'g1' })
    await db.table('goalTasks').put({ ...note(), _localId: 't1', _localGoalId: 'g1', goal_id: 42 })
    await saveLocalOperation('goals', 'delete', 'g1')
    const op = await firstClaim()
    expect(await db.goalTasks.count()).toBe(1)
    await acknowledgeOperation(op, undefined)
    expect(await db.goals.count()).toBe(0)
    expect(await db.goalTasks.count()).toBe(0)
  })
  it('refuses new tasks under a goal that is being deleted', async () => {
    await db.table('goals').put({ ...note(), _localId: 'g1', _syncStatus: 'pending_delete' })
    await expect(saveLocalOperation('goalTasks', 'create', 't1', { ...note(), _localId: 't1', _localGoalId: 'g1' })).rejects.toThrow('不能添加任务')
    expect(await db.goalTasks.count()).toBe(0)
    expect(await db.opQueue.count()).toBe(0)
  })
  it('applies an accepted remote goal deletion to its local children atomically', async () => {
    vi.stubGlobal('fetch', vi.fn(async (url: string) => url.startsWith('/api/sync/goals/') ? new Response('{}', { status: 404 }) : response([])))
    engine = new SyncEngine(); engine.registerAdapter(goalsSyncAdapter); engine.start(); await engine.syncAll()
    await db.table('goals').put({ ...note(), _localId: 'g1', _syncStatus: 'conflicted', _conflictAt: now, _conflictOpType: 'delete' })
    await db.table('goalTasks').put({ ...note(), _localId: 't1', _localGoalId: 'g1', goal_id: 42 })
    await saveLocalOperation('goalTasks', 'update', 't1', { title: 'child edit' })
    await engine.resolveConflict('goals', 'g1', 'use_server')
    expect(await db.goals.count()).toBe(0)
    expect(await db.goalTasks.count()).toBe(0)
    expect(await db.opQueue.count()).toBe(0)
  })
})

describe('response loss and safe replays', () => {
  it.each(['update', 'delete'] as const)('replays a lost create before its subsequent %s, even after restart', async (nextAction) => {
    const receipts = new Map<string, unknown>()
    let remote: ReturnType<typeof serverNote> | null = null
    let creations = 0
    let loseResponse = true
    const writes: { key: string; method: string; body: string | undefined; match: string | null }[] = []
    vi.stubGlobal('fetch', vi.fn(async (url: string, options?: RequestInit) => {
      if (url === '/api/sync/capabilities') return response({ protocol_version: 1 })
      if (!options?.method) return response(remote ? [remote] : [])
      const headers = new Headers(options.headers)
      const key = headers.get('Idempotency-Key')!
      writes.push({ key, method: options.method, body: options.body as string, match: headers.get('If-Match') })
      if (receipts.has(key)) return response(receipts.get(key))
      let result: unknown
      if (options.method === 'POST') {
        creations++; remote = serverNote(JSON.parse(options.body as string).title)
        result = remote
      } else if (options.method === 'PUT') {
        expect(headers.get('If-Match')).toBe('"1"')
        remote = serverNote(JSON.parse(options.body as string).title, 2); result = remote
      } else {
        expect(headers.get('If-Match')).toBe('"1"')
        remote = null; result = { ok: true }
      }
      receipts.set(key, result)
      if (loseResponse) { loseResponse = false; throw new TypeError('committed, response lost') }
      return response(result)
    }))
    await saveLocalOperation('notes', 'create', 'n1', note({ _serverId: null }))
    engine = new SyncEngine(); engine.registerAdapter(notesSyncAdapter); engine.start()
    // Observe one initial pass without requesting another retry in that pass.
    await vi.waitFor(() => expect(engine?.getSnapshot().status).toBe('offline'))
    engine.stop()
    await saveLocalOperation('notes', nextAction, 'n1', nextAction === 'update' ? { title: 'edited after lost response' } : {})
    expect((await db.opQueue.toArray())[0].claimedAt).toBeTruthy()
    closeStudyDatabase(); await openStudyDatabase(user); setApiSessionUser(user.id)
    engine = new SyncEngine(); engine.registerAdapter(notesSyncAdapter); engine.start(); await engine.syncAll()
    expect(creations).toBe(1)
    expect(writes[0]).toEqual(writes[1])
    expect(await db.opQueue.count()).toBe(0)
    if (nextAction === 'delete') expect(await db.notes.count()).toBe(0)
    else expect(await db.notes.get('n1')).toMatchObject({ title: 'edited after lost response', _syncStatus: 'synced', _serverId: 42, _serverVersion: 2 })
  })
  it('fails closed before any mutation against an old server', async () => {
    await saveLocalOperation('notes', 'create', 'n1', note({ _serverId: null }))
    const op = await firstClaim()
    const fetch = vi.fn(async () => new Response('not found', { status: 404 }))
    vi.stubGlobal('fetch', fetch)
    await expect(notesSyncAdapter.pushCreate(op)).rejects.toMatchObject({ status: 426 })
    expect(fetch).toHaveBeenCalledTimes(1)
    expect(await db.opQueue.count()).toBe(1)
  })
})

describe('pull reconciliation and UTC boundaries', () => {
  it('does not overwrite an edit made while a list request is pending', async () => {
    await db.notes.put(note())
    let finish!: (res: Response) => void
    vi.stubGlobal('fetch', vi.fn(() => new Promise<Response>(resolve => { finish = resolve })))
    const pull = notesSyncAdapter.pullAll()
    await vi.waitFor(() => expect(finish).toBeDefined())
    await saveLocalOperation('notes', 'update', 'n1', { title: 'keep local' })
    finish(response([serverNote('stale response')]))
    await pull
    expect((await db.notes.get('n1'))?.title).toBe('keep local')
    expect(await db.opQueue.count()).toBe(1)
  })
  it('does not erase a create acknowledged after an earlier empty snapshot started', async () => {
    let finish!: (res: Response) => void
    vi.stubGlobal('fetch', vi.fn(() => new Promise<Response>(resolve => { finish = resolve })))
    const pull = notesSyncAdapter.pullAll()
    await vi.waitFor(() => expect(finish).toBeDefined())
    await saveLocalOperation('notes', 'create', 'n1', note({ _serverId: null }))
    const op = await firstClaim()
    await acknowledgeOperation(op, { server: serverNote() }, notesSyncAdapter.mapServer)
    finish(response([])); await pull
    expect((await db.notes.get('n1'))?._serverId).toBe(42)
  })
  it.each([ankiCardsSyncAdapter, wrongQuestionsSyncAdapter])('never infers deletion from the capped $module page', async adapter => {
    await db.table(adapter.module).put(note())
    vi.stubGlobal('fetch', vi.fn(async () => response([])))
    await adapter.pullAll()
    expect(await db.table(adapter.module).get('n1')).toBeDefined()
  })
  it('treats naive datetime as UTC and offset time as the same instant', () => {
    expect(utcTimestamp('2026-09-12T12:00:00')).toBe(now)
    expect(utcTimestamp('2026-09-12T20:00:00+08:00')).toBe(now)
    expect(utcTimestamp('2026-09-12')).toBeNull()
    expect(utcTimestamp('bad timestamp')).toBeNull()
  })
  it('does not auto-replay uncertain creates when upgrading a version4 database', async () => {
    const legacyUser = { id: 899, created_at: user.created_at }
    const legacy = new Dexie(studyDatabaseName(legacyUser))
    legacy.version(4).stores({
      notes: '_localId, _serverId, _syncStatus, _updatedAt', goals: '_localId, _serverId, _syncStatus, _updatedAt, status',
      goalTasks: '_localId, _serverId, _syncStatus, _updatedAt, goal_id, _localGoalId, parent_task_id, planned_date, status',
      ankiCards: '_localId, _serverId, _syncStatus, _updatedAt, due_at', wrongQuestions: '_localId, _serverId, _syncStatus, _updatedAt',
      opQueue: '++id, module, localId, [module+localId], createdAt',
    })
    await legacy.table('notes').put(note({ _serverId: null, _syncStatus: 'pending_create' }))
    await legacy.table('opQueue').add({ module: 'notes', localId: 'n1', opType: 'create', payload: JSON.stringify(note()), createdAt: now })
    legacy.close(); await openStudyDatabase(legacyUser)
    const op = (await db.opQueue.toArray())[0]
    expect(op.legacyUncertain).toBe(true)
    expect(await claimOperation(op.id!)).toBeUndefined()
    expect((await db.notes.get('n1'))?.content).toBe('private content')
  })
})
