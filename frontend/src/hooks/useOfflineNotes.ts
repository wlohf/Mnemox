import { useLiveQuery } from 'dexie-react-hooks'
import { db, type LocalNote } from '../db/studyDb'
import { enqueueOperation } from '../sync/enqueueOperation'
import { syncEngine } from '../sync/SyncEngine'

export interface OfflineNoteItem {
  _localId: string
  _serverId: number | null
  _syncStatus: string
  title: string
  content: string
  note_type: string | null
  material_id: number | null
  chapter_id: number | null
  tags: string[]
  links: Array<{ id?: number; link_type: string; link_id: number }>
  created_at: string | null
  updated_at: string
}

function toOfflineItem(local: LocalNote): OfflineNoteItem {
  return {
    _localId: local._localId,
    _serverId: local._serverId,
    _syncStatus: local._syncStatus,
    title: local.title,
    content: local.content,
    note_type: local.note_type,
    material_id: local.material_id,
    chapter_id: local.chapter_id,
    tags: safeParse(local.tags, []),
    links: safeParse(local.links, []),
    created_at: local.created_at,
    updated_at: local._updatedAt,
  }
}

function safeParse<T>(json: string | null | undefined, fallback: T): T {
  if (!json) return fallback
  try {
    return JSON.parse(json)
  } catch {
    return fallback
  }
}

export function useOfflineNotes(params?: { q?: string; tag?: string }) {
  const allNotes = useLiveQuery(
    () =>
      db.notes
        .where('_syncStatus')
        .notEqual('pending_delete')
        .toArray(),
    [],
    [] as LocalNote[],
  )

  // Client-side filtering
  let filtered = allNotes
  if (params?.q) {
    const lower = params.q.toLowerCase()
    filtered = filtered.filter(
      (n) =>
        n.title.toLowerCase().includes(lower) ||
        n.content.toLowerCase().includes(lower),
    )
  }
  if (params?.tag) {
    const tag = params.tag
    filtered = filtered.filter((n) => {
      const tags: string[] = safeParse(n.tags, [])
      return tags.includes(tag)
    })
  }

  // Sort by _updatedAt descending
  filtered.sort((a, b) => (b._updatedAt > a._updatedAt ? 1 : -1))

  const notes: OfflineNoteItem[] = filtered.map(toOfflineItem)

  const createNote = async (data: {
    title: string
    content: string
    note_type?: string
    material_id?: number
    chapter_id?: number
    tags?: string[]
    links?: Array<{ link_type: string; link_id: number }>
  }): Promise<OfflineNoteItem> => {
    const now = new Date().toISOString()
    const localId = crypto.randomUUID()
    const record: LocalNote = {
      _localId: localId,
      _serverId: null,
      _syncStatus: 'pending_create',
      _updatedAt: now,
      _lastSyncedAt: null,
      _conflictAt: null,
      _conflictServerData: null,
      title: data.title,
      content: data.content,
      note_type: data.note_type ?? 'general',
      material_id: data.material_id ?? null,
      chapter_id: data.chapter_id ?? null,
      tags: JSON.stringify(data.tags ?? []),
      links: JSON.stringify(data.links ?? []),
      created_at: now,
    }
    await db.notes.put(record)
    await enqueueOperation('notes', 'create', localId, record as unknown as Record<string, unknown>)
    void syncEngine.syncAll()
    return toOfflineItem(record)
  }

  const updateNote = async (
    localId: string,
    data: Record<string, unknown>,
  ): Promise<OfflineNoteItem | null> => {
    const existing = await db.notes.get(localId)
    if (!existing) return null

    const now = new Date().toISOString()
    const updates: Partial<LocalNote> = { _updatedAt: now }

    if (data.title !== undefined) updates.title = data.title as string
    if (data.content !== undefined) updates.content = data.content as string
    if (data.note_type !== undefined) updates.note_type = data.note_type as string | null
    if (data.tags !== undefined) updates.tags = JSON.stringify(data.tags)

    if (existing._syncStatus === 'synced') {
      updates._syncStatus = 'pending_update'
    }
    // If pending_create, keep it as pending_create (merge logic handles it)

    await db.notes.update(localId, updates)

    const queuePayload: Record<string, unknown> = { ...updates }
    // For the queue we store tags as JSON string
    if (data.tags !== undefined) queuePayload.tags = JSON.stringify(data.tags)

    await enqueueOperation(
      'notes',
      existing._syncStatus === 'pending_create' ? 'update' : 'update',
      localId,
      queuePayload,
    )
    void syncEngine.syncAll()

    const updated = await db.notes.get(localId)
    return updated ? toOfflineItem(updated) : null
  }

  const deleteNote = async (localId: string): Promise<boolean> => {
    const existing = await db.notes.get(localId)
    if (!existing) return false

    if (existing._syncStatus === 'pending_create') {
      // Never pushed to server — just delete locally
      await db.notes.delete(localId)
      await enqueueOperation('notes', 'delete', localId)
      return true
    }

    // Mark as pending_delete so it disappears from UI immediately
    await db.notes.update(localId, { _syncStatus: 'pending_delete' })
    await enqueueOperation('notes', 'delete', localId)
    void syncEngine.syncAll()
    return true
  }

  return { notes, createNote, updateNote, deleteNote }
}
