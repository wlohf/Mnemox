import { db, type LocalNote, type QueuedOperation } from '../../db/studyDb'
import type { ModuleSyncAdapter } from '../SyncEngine'
import { apiFetch } from '../../services/apiClient'

interface ServerNote {
  id: number
  title: string
  content: string
  note_type: string | null
  material_id: number | null
  chapter_id: number | null
  tags: string[]
  links: Array<{ id?: number; link_type: string; link_id: number }>
  created_at: string | null
  updated_at: string | null
}

export const notesSyncAdapter: ModuleSyncAdapter = {
  module: 'notes',

  async pushCreate(op: QueuedOperation) {
    const payload = JSON.parse(op.payload) as Record<string, unknown>
    const body = {
      title: payload.title ?? '',
      content: payload.content ?? '',
      note_type: payload.note_type ?? 'general',
      material_id: payload.material_id ?? undefined,
      chapter_id: payload.chapter_id ?? undefined,
      tags: payload.tags ? JSON.parse(payload.tags as string) : [],
      links: payload.links ? JSON.parse(payload.links as string) : [],
    }

    const server = await apiFetch<ServerNote>('/api/notes', {
      method: 'POST',
      body: JSON.stringify(body),
    })

    await db.notes.update(op.localId, {
      _serverId: server.id,
      _syncStatus: 'synced',
      _lastSyncedAt: new Date().toISOString(),
      _updatedAt: server.updated_at ?? new Date().toISOString(),
    })
  },

  async pushUpdate(op: QueuedOperation) {
    const local = await db.notes.get(op.localId)
    if (!local || !local._serverId) throw new Error('Cannot push update: no serverId')

    const payload = JSON.parse(op.payload) as Record<string, unknown>
    const body: Record<string, unknown> = {}
    if (payload.title !== undefined) body.title = payload.title
    if (payload.content !== undefined) body.content = payload.content
    if (payload.note_type !== undefined) body.note_type = payload.note_type
    if (payload.tags !== undefined) body.tags = JSON.parse(payload.tags as string)

    const server = await apiFetch<ServerNote>(`/api/notes/${local._serverId}`, {
      method: 'PUT',
      body: JSON.stringify(body),
    })

    await db.notes.update(op.localId, {
      _syncStatus: 'synced',
      _lastSyncedAt: new Date().toISOString(),
      _updatedAt: server.updated_at ?? new Date().toISOString(),
    })
  },

  async pushDelete(op: QueuedOperation) {
    const local = await db.notes.get(op.localId)
    if (!local) return
    if (!local._serverId) {
      await db.notes.delete(op.localId)
      return
    }

    try {
      await apiFetch(`/api/notes/${local._serverId}`, { method: 'DELETE' })
    } catch {
      // 404 means already deleted on server — that's fine, other errors will propagate
    }
    await db.notes.delete(op.localId)
  },

  async pullAll() {
    const serverNotes = await apiFetch<ServerNote[]>('/api/notes')
    const serverMap = new Map(serverNotes.map((n) => [n.id, n]))

    const allLocal = await db.notes.toArray()
    const localByServerId = new Map<number, LocalNote>()
    for (const l of allLocal) {
      if (l._serverId != null) localByServerId.set(l._serverId, l)
    }

    // Upsert server records into local
    for (const sn of serverNotes) {
      const local = localByServerId.get(sn.id)
      const serverUpdatedAt = sn.updated_at ?? sn.created_at ?? new Date().toISOString()

      if (!local) {
        // New record from server
        await db.notes.put({
          _localId: crypto.randomUUID(),
          _serverId: sn.id,
          _syncStatus: 'synced',
          _updatedAt: serverUpdatedAt,
          _lastSyncedAt: new Date().toISOString(),
          _conflictAt: null,
          _conflictServerData: null,
          title: sn.title,
          content: sn.content,
          note_type: sn.note_type,
          material_id: sn.material_id,
          chapter_id: sn.chapter_id,
          tags: JSON.stringify(sn.tags ?? []),
          links: JSON.stringify(sn.links ?? []),
          created_at: sn.created_at,
        })
      } else if (local._syncStatus === 'synced') {
        // Overwrite with server data
        await db.notes.update(local._localId, {
          title: sn.title,
          content: sn.content,
          note_type: sn.note_type,
          material_id: sn.material_id,
          chapter_id: sn.chapter_id,
          tags: JSON.stringify(sn.tags ?? []),
          links: JSON.stringify(sn.links ?? []),
          _updatedAt: serverUpdatedAt,
          _lastSyncedAt: new Date().toISOString(),
          created_at: sn.created_at,
        })
      } else if (local._syncStatus === 'pending_update') {
        // LWW: compare timestamps
        if (serverUpdatedAt > local._updatedAt) {
          // Server wins — overwrite and clear pending ops
          await db.notes.update(local._localId, {
            title: sn.title,
            content: sn.content,
            note_type: sn.note_type,
            material_id: sn.material_id,
            chapter_id: sn.chapter_id,
            tags: JSON.stringify(sn.tags ?? []),
            links: JSON.stringify(sn.links ?? []),
            _syncStatus: 'synced',
            _updatedAt: serverUpdatedAt,
            _lastSyncedAt: new Date().toISOString(),
          })
          // Remove pending ops for this record
          await db.opQueue.where({ module: 'notes', localId: local._localId }).delete()
        }
        // else local wins — keep pending op for next push
      }
      // pending_delete → keep delete intent, don't overwrite
      // pending_create → shouldn't have a serverId, skip
    }

    // Detect server-side deletions: local synced records whose serverId is no longer on server
    for (const local of allLocal) {
      if (local._serverId != null && local._syncStatus === 'synced' && !serverMap.has(local._serverId)) {
        await db.notes.delete(local._localId)
      }
    }
  },
}
