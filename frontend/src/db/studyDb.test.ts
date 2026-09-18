import 'fake-indexeddb/auto'
import Dexie from 'dexie'
import { afterEach, describe, expect, it } from 'vitest'
import { db, openStudyDatabase, closeStudyDatabase, studyDatabaseName } from './studyDb'

const alice = { id: 101, created_at: '2026-09-12T00:00:00Z' }
const bob = { id: 102, created_at: '2026-09-12T00:00:00Z' }
afterEach(async () => {
  closeStudyDatabase()
  for (const name of await Dexie.getDatabaseNames()) await Dexie.delete(name)
})

describe('account-partitioned offline database', () => {
  it('keeps A pending operations out of B and restores them when A returns', async () => {
    await openStudyDatabase(alice)
    await db.opQueue.add({ module: 'notes', opType: 'create', localId: 'alice-note', payload: '{"title":"private A"}', createdAt: new Date().toISOString() })
    const oldDb = db
    await openStudyDatabase(bob)
    expect(db.name).not.toBe(oldDb.name)
    expect(await db.opQueue.count()).toBe(0)
    await expect(oldDb.opQueue.toArray()).rejects.toMatchObject({ name: 'DatabaseClosedError' })
    closeStudyDatabase()
    await openStudyDatabase(alice)
    expect((await db.opQueue.toArray())[0].localId).toBe('alice-note')
  })

  it('does not auto-adopt or erase the legacy unowned queue', async () => {
    const legacy = new Dexie('StudyAssistantDB')
    legacy.version(1).stores({ opQueue: '++id' })
    await legacy.table('opQueue').add({ payload: 'unowned private note' })
    legacy.close()
    await openStudyDatabase(bob)
    expect(await db.opQueue.count()).toBe(0)
    await legacy.open()
    expect(await legacy.table('opQueue').count()).toBe(1)
    legacy.close()
  })

  it('disallows unauthenticated access and distinguishes reused server IDs', async () => {
    closeStudyDatabase()
    await expect(db.opQueue.toArray()).rejects.toMatchObject({ name: 'DatabaseClosedError' })
    expect(studyDatabaseName(alice)).not.toBe(studyDatabaseName({ ...alice, created_at: '2026-09-13T00:00:00Z' }))
    expect(() => studyDatabaseName({ id: 0, created_at: '' })).toThrow('归属')
  })
})
