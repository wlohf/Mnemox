import { db, type LocalAnkiCard, type QueuedOperation } from '../../db/studyDb'
import type { ModuleSyncAdapter } from '../SyncEngine'
import { apiFetch } from '../../services/apiClient'
import type { AnkiCardItem } from '../../services/ankiApi'

export const ankiCardsSyncAdapter: ModuleSyncAdapter = {
  module: 'ankiCards',

  async pushCreate(op: QueuedOperation) {
    const payload = JSON.parse(op.payload) as Record<string, unknown>
    const server = await apiFetch<AnkiCardItem>('/api/anki/cards', {
      method: 'POST',
      body: JSON.stringify({ front: payload.front, back: payload.back, tags: payload.tags, note: payload.note }),
    })
    await db.ankiCards.update(op.localId, {
      _serverId: server.id,
      _syncStatus: 'synced',
      _lastSyncedAt: new Date().toISOString(),
    })
  },

  async pushUpdate(op: QueuedOperation) {
    const local = await db.ankiCards.get(op.localId)
    if (!local?._serverId) throw new Error('no serverId')
    const payload = JSON.parse(op.payload) as Record<string, unknown>
    await apiFetch<AnkiCardItem>(`/api/anki/cards/${local._serverId}`, {
      method: 'PUT',
      body: JSON.stringify(payload),
    })
    await db.ankiCards.update(op.localId, { _syncStatus: 'synced', _lastSyncedAt: new Date().toISOString() })
  },

  async pushDelete(op: QueuedOperation) {
    const local = await db.ankiCards.get(op.localId)
    if (!local) return
    if (local._serverId) {
      try { await apiFetch(`/api/anki/cards/${local._serverId}`, { method: 'DELETE' }) } catch { /* 404 ok */ }
    }
    await db.ankiCards.delete(op.localId)
  },

  async pullAll() {
    const serverCards = await apiFetch<AnkiCardItem[]>('/api/anki/cards?scope=all&limit=200')
    const serverMap = new Map(serverCards.map((c) => [c.id, c]))
    const allLocal = await db.ankiCards.toArray()
    const localByServerId = new Map<number, LocalAnkiCard>()
    for (const l of allLocal) { if (l._serverId != null) localByServerId.set(l._serverId, l) }

    for (const sc of serverCards) {
      const local = localByServerId.get(sc.id)
      const updatedAt = sc.created_at ?? new Date().toISOString()
      if (!local) {
        await db.ankiCards.put({
          _localId: crypto.randomUUID(), _serverId: sc.id, _syncStatus: 'synced',
          _updatedAt: updatedAt, _lastSyncedAt: new Date().toISOString(),
          _conflictAt: null, _conflictServerData: null,
          front: sc.front, back: sc.back, source: sc.source, tags: sc.tags ?? null,
          note: sc.note ?? null, due_at: sc.due_at ?? null,
          interval_days: sc.interval_days, ease_factor: sc.ease_factor,
          repetitions: sc.repetitions, last_quality: sc.last_quality ?? null,
          created_at: sc.created_at ?? null,
        })
      } else if (local._syncStatus === 'synced') {
        await db.ankiCards.update(local._localId, {
          front: sc.front, back: sc.back, tags: sc.tags ?? null, note: sc.note ?? null,
          due_at: sc.due_at ?? null, interval_days: sc.interval_days,
          ease_factor: sc.ease_factor, repetitions: sc.repetitions,
          last_quality: sc.last_quality ?? null, _updatedAt: updatedAt,
          _lastSyncedAt: new Date().toISOString(),
        })
      }
    }

    for (const local of allLocal) {
      if (local._serverId != null && local._syncStatus === 'synced' && !serverMap.has(local._serverId)) {
        await db.ankiCards.delete(local._localId)
      }
    }
  },
}
