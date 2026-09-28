import 'fake-indexeddb/auto'
import Dexie from 'dexie'
import { beforeEach, afterEach, expect, it } from 'vitest'
import { db, openStudyDatabase, closeStudyDatabase } from '../db/studyDb'
import { createLocalAnkiCard, queueAnkiReview } from './offlineAnki'
import { claimOperation, saveLocalOperation } from '../sync/enqueueOperation'
import { acknowledgeOperation } from '../sync/syncProtocol'
import { fetchAllPages } from './pagedCollection'

const user = { id: 984, created_at: '2026-09-25T00:00:00Z' }
beforeEach(async () => { await openStudyDatabase(user) })
afterEach(async () => {
  closeStudyDatabase()
  for (const name of await Dexie.getDatabaseNames()) await Dexie.delete(name)
})

it('persists offline creation and one review across restart, preserving a lost-response retry', async () => {
  const card = await createLocalAnkiCard({ front: '问题', back: '回答' })
  await Promise.all([queueAnkiReview(card._localId, 4), queueAnkiReview(card._localId, 4)])
  let operations = await db.opQueue.toArray()
  expect(operations.map(op => op.opType)).toEqual(['create', 'review'])
  expect(await claimOperation(operations[1].id!)).toBeUndefined()
  const originalReviewId = operations[1].operationId
  closeStudyDatabase(); await openStudyDatabase(user)
  expect((await db.ankiCards.get(card._localId))?.front).toBe('问题')
  const create = (await claimOperation(operations[0].id!))!
  await acknowledgeOperation(create, { server: { id: 20, sync_version: 1 } })
  const review = (await claimOperation(operations[1].id!))!
  expect(review).toMatchObject({ operationId: originalReviewId, serverId: 20, expectedVersion: 1 })
  closeStudyDatabase(); await openStudyDatabase(user)
  expect(await claimOperation(review.id!)).toEqual(review)
  await expect(saveLocalOperation('ankiCards', 'update', card._localId, { front: 'edit' })).rejects.toThrow('等待确认')
  await acknowledgeOperation(review, { server: { id: 20, sync_version: 2, repetitions: 1 } }, server => ({ repetitions: server.repetitions }))
  expect(await db.opQueue.count()).toBe(0)
  expect(await db.ankiCards.get(card._localId)).toMatchObject({ _syncStatus: 'synced', repetitions: 1 })
  closeStudyDatabase(); await openStudyDatabase({ ...user, id: 985 })
  expect(await db.ankiCards.count()).toBe(0)
})

it('loads beyond 200 rows with ID cursors, including deletions between pages', async () => {
  const rows = Array.from({ length: 451 }, (_, i) => ({ id: i + 1 }))
  const cursors: number[] = []
  const fetch = async <T,>(url: string): Promise<T> => {
    const after = Number(new URL(url, 'http://localhost').searchParams.get('after_id'))
    cursors.push(after)
    if (after > 0) rows.splice(0, 1)
    return rows.filter(row => row.id > after).slice(0, 200) as T
  }
  expect((await fetchAllPages('/cards', fetch)).map(row => row.id)).toEqual(Array.from({ length: 451 }, (_, i) => i + 1))
  expect(cursors).toEqual([0, 200, 400])
})

it('rejects an old server that repeats the first page', async () => {
  const fetch = async <T,>(): Promise<T> => Array.from({ length: 200 }, (_, i) => ({ id: i + 1 })) as T
  await expect(fetchAllPages('/cards', fetch)).rejects.toThrow('分页协议不兼容')
})
