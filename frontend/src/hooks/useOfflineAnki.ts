import { useLiveQuery } from 'dexie-react-hooks'
import { db as activeDb, type LocalAnkiCard } from '../db/studyDb'
import { createLocalAnkiCard, queueAnkiReview } from '../services/offlineAnki'
import { saveLocalOperation } from '../sync/enqueueOperation'
import { syncEngine } from '../sync/SyncEngine'

export function useOfflineAnki() {
  const db = activeDb
  const cards = useLiveQuery(() => db.ankiCards.where('_syncStatus').notEqual('pending_delete').toArray(), [db], [] as LocalAnkiCard[])
  const pendingReviews = useLiveQuery(async () => new Set((await db.opQueue.where('module').equals('ankiCards').toArray())
    .filter(op => op.opType === 'review').map(op => op.localId)), [db], new Set<string>())
  return {
    cards, pendingReviews,
    async createCard(data: { front: string; back: string; tags?: string }) {
      await createLocalAnkiCard(data, db)
      void syncEngine.syncAll()
    },
    async updateCard(id: string, data: { front: string; back: string; tags?: string }) {
      if (!await saveLocalOperation('ankiCards', 'update', id, data, db)) throw new Error('卡片不存在')
      void syncEngine.syncAll()
    },
    async deleteCard(id: string) {
      await saveLocalOperation('ankiCards', 'delete', id, {}, db)
      void syncEngine.syncAll()
    },
    async reviewCard(id: string, quality: number) {
      await queueAnkiReview(id, quality, db)
      void syncEngine.syncAll()
    },
  }
}
